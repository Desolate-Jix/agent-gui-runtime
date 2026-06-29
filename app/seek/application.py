from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.gate.danger import scoped_final_submit_visible_blocker


FINAL_SUBMIT_TERMS = {
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
REVIEW_STEP_TERMS = {"review and submit", "review your application", "review application", "application review"}
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
APPLICATION_FLOW_START_TERMS = {
    "apply with seek",
    "choose documents",
    "answer employer questions",
    "update seek profile",
    "review and submit",
    "cover letter",
    "resume",
    "cv",
}

SEEK_INTERNAL_PLAN_STATES = {
    "cover_letter_field_detected",
    "application_form_detected",
    "profile_review_detected",
    "screening_questions_detected",
}
SEEK_INTERNAL_BLOCKED_STATES = {
    "final_submit_visible",
    "review_step_detected",
    "resume_upload_required",
    "risky_application_questions",
}
HARD_BLOCKED_STATES = {
    "login_required",
    "captcha_or_verification",
    "unknown_after_apply",
}


def assess_seek_application_flow_state(
    observation: dict[str, Any] | None,
    *,
    source_job: dict[str, Any] | None = None,
    post_fill_context: bool = False,
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
    form_inventory = _application_form_inventory(items)
    current_step = _current_seek_application_step(items)
    seek_apply_route_visible = "seek.com/job/" in haystack and "/apply" in haystack
    active_flow_started = (
        bool(post_fill_context)
        or
        bool(current_step)
        or seek_apply_route_visible
        or _contains_any(
            haystack,
            APPLICATION_FLOW_START_TERMS | REVIEW_STEP_TERMS | COVER_LETTER_TERMS,
        )
    )
    final_submit_blocker = _final_submit_visible_blocker(items, active_flow_started=active_flow_started)

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
    elif _upload_required(haystack):
        state_type = "resume_upload_required"
        stop_reason = "resume_or_attachment_upload_requires_user_review"
        flags.append("resume_upload_required")
        detected_states.append("resume_upload_required")
    elif current_step == "review_and_submit":
        state_type = "review_step_detected"
        stop_reason = "review_step_stop_before_final_submit"
        detected_states.append("review_step_detected")
    elif active_flow_started and _form_fields_contain_any(form_inventory, RISKY_FORM_TERMS):
        state_type = "risky_application_questions"
        stop_reason = "risky_application_questions_require_user_or_gpt_decision"
        flags.append("risky_questions_present")
        detected_states.append("risky_application_questions")
    elif active_flow_started and form_inventory["screening_questions_detected"]:
        state_type = "screening_questions_detected"
        stop_reason = "screening_questions_stop_before_form_fill"
        detected_states.append("screening_questions_detected")
    elif active_flow_started and form_inventory["cover_letter_field_detected"]:
        state_type = "cover_letter_field_detected"
        stop_reason = "cover_letter_field_detected_stop_before_paste"
        detected_states.append("cover_letter_field_detected")
    elif _review_step_is_current(items, haystack, current_step=current_step):
        state_type = "review_step_detected"
        stop_reason = "review_step_stop_before_final_submit"
        detected_states.append("review_step_detected")
    elif current_step == "update_seek_profile":
        state_type = "profile_review_detected"
        stop_reason = "profile_review_detected_continue_without_profile_mutation"
        detected_states.append("profile_review_detected")
    elif active_flow_started and form_inventory["application_form_detected"]:
        state_type = "application_form_detected"
        stop_reason = "application_form_detected_stop_before_form_fill"
        detected_states.append("application_form_detected")
    elif seek_apply_route_visible:
        state_type = "application_flow_opened"
        stop_reason = "seek_apply_route_opened_wait_for_form_or_user_review"
        detected_states.append("seek_apply_route_detected")
    elif _contains_any(haystack, APPLICATION_FLOW_START_TERMS):
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
        "current_step": current_step,
        "application_form_inventory": form_inventory,
        "trace_path": payload.get("trace_path"),
        "source_job": {
            "job_id": (source_job or {}).get("job_id"),
            "title": (source_job or {}).get("title"),
            "company": (source_job or {}).get("company"),
        },
        "context": {
            "post_fill_context": bool(post_fill_context),
        },
        "evidence": {
            "texts": texts[:120],
            "text_count": len(texts),
        },
    }


def build_seek_apply_flow_decision(application_flow_state: dict[str, Any] | None) -> dict[str, Any]:
    """Decide which downstream Apply Entry stages are allowed after classifying the page."""

    flow = application_flow_state if isinstance(application_flow_state, dict) else {}
    source_state_type = str(flow.get("state_type") or "unknown_after_apply")
    final_submit_blocker = flow.get("final_submit_visible_blocker") if isinstance(flow.get("final_submit_visible_blocker"), dict) else {}
    evidence = flow.get("evidence") if isinstance(flow.get("evidence"), dict) else {}
    texts = [str(item) for item in evidence.get("texts") or [] if str(item or "").strip()]

    if source_state_type == "third_party_ats":
        state_type = "third_party_ats_deferred"
        decision = "stop"
        reason = "third_party_ats_deferred"
        allowed_next_steps = ["capture", "back_to_seek", "match"]
        blocked_downstream = _blocked_downstream(all_blocked=True)
    elif final_submit_blocker.get("blocked") is True or source_state_type == "final_submit_visible":
        state_type = "seek_internal_final_submit_visible"
        decision = "stop"
        reason = "final_submit_visible_stop_before_submission"
        allowed_next_steps = ["capture", "back_to_seek", "match"]
        blocked_downstream = _blocked_downstream(all_blocked=True)
    elif source_state_type in SEEK_INTERNAL_PLAN_STATES:
        state_type = f"seek_internal_{source_state_type}"
        decision = "continue_read_only"
        reason = "seek_internal_read_only_planning_allowed"
        allowed_next_steps = ["generate_answer_plan", "capture", "back_to_seek", "match"]
        blocked_downstream = {
            "cover_letter_draft": False,
            "answer_plan": False,
            "safe_fill": False,
            "submit": True,
        }
    elif source_state_type == "application_flow_opened":
        state_type = "seek_internal_application_flow_opened_waiting_for_form"
        decision = "wait_for_form_readiness"
        reason = "seek_apply_route_opened_wait_for_form_or_user_review"
        allowed_next_steps = ["observe_application_form", "capture", "back_to_seek", "match"]
        blocked_downstream = {
            "cover_letter_draft": True,
            "answer_plan": True,
            "safe_fill": True,
            "submit": True,
        }
    elif source_state_type in SEEK_INTERNAL_BLOCKED_STATES:
        state_type = f"seek_internal_{source_state_type}_blocked"
        decision = "stop"
        reason = f"{source_state_type}_blocked"
        allowed_next_steps = ["capture", "back_to_seek", "match"]
        blocked_downstream = _blocked_downstream(all_blocked=True)
    elif source_state_type in HARD_BLOCKED_STATES:
        state_type = f"{source_state_type}_blocked"
        decision = "stop"
        reason = f"{source_state_type}_blocked"
        allowed_next_steps = ["capture", "back_to_seek", "match"]
        blocked_downstream = _blocked_downstream(all_blocked=True)
    else:
        state_type = "unknown_application_state_blocked"
        decision = "stop"
        reason = "unknown_application_state_blocked"
        allowed_next_steps = ["capture", "back_to_seek", "match"]
        blocked_downstream = _blocked_downstream(all_blocked=True)

    return {
        "contract_version": "seek_apply_flow_decision_v1",
        "source_state_type": source_state_type,
        "state_type": state_type,
        "decision": decision,
        "reason": reason,
        "allowed_next_steps": allowed_next_steps,
        "blocked_downstream": blocked_downstream,
        "surface": {
            "same_domain": source_state_type != "third_party_ats",
            "detected_ats_terms": _detected_terms(" ".join(texts).casefold(), THIRD_PARTY_ATS_TERMS),
            "trace_path": flow.get("trace_path"),
        },
        "safety_counters": {
            "forms_filled": 0,
            "submit_clicks": 0,
            "final_submissions": 0,
        },
        "final_submit_visible_blocker": final_submit_blocker or None,
    }


def build_seek_application_final_review_audit(
    fill_record: dict[str, Any] | None,
    *,
    base_dir: Path | str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Audit a SEEK station-internal application fill that must stop before final submit."""

    record = fill_record if isinstance(fill_record, dict) else {}
    fields = [field for field in record.get("filled_fields") or [] if isinstance(field, dict)]
    evidence = record.get("evidence") if isinstance(record.get("evidence"), dict) else {}

    answered_question_fields = [
        field
        for field in fields
        if str(field.get("step") or "") == "answer_employer_questions" and str(field.get("value") or "").strip()
    ]
    expected_question_total = int(record.get("employer_question_total") or len(answered_question_fields) or 0)
    answered_question_count = len(answered_question_fields)
    persistent_profile_updates = [
        field
        for field in fields
        if str(field.get("step") or "") == "update_seek_profile"
        and str(field.get("policy") or "") != "do_not_mutate_profile_without_explicit_user_approval"
    ]
    seek_profile_suggestion_choices = [
        str(field.get("value") or "")
        for field in fields
        if str(field.get("step") or "") == "update_seek_profile"
        and _is_seek_profile_suggestion_field(field)
    ]
    seek_profile_suggestions_present = any(
        str(field.get("step") or "") == "update_seek_profile" and _is_seek_profile_suggestion_field(field)
        for field in fields
    )
    cover_letter_field = next(
        (
            field
            for field in fields
            if str(field.get("step") or "") == "choose_documents" and str(field.get("field") or "") == "cover_letter"
        ),
        None,
    )
    resume_field = next(
        (
            field
            for field in fields
            if str(field.get("step") or "") == "choose_documents" and str(field.get("field") or "") == "resume"
        ),
        None,
    )
    final_submit_clicked = bool(evidence.get("final_submit_clicked") or record.get("final_submit_clicked"))
    submit_clicks = int(record.get("submit_clicks") or (1 if final_submit_clicked else 0))
    final_submissions = int(record.get("final_submissions") or (1 if final_submit_clicked else 0))
    review_screenshot = evidence.get("review_before_submit_screenshot")
    cover_letter_trace = evidence.get("clipboard_fix_type_text_trace") or evidence.get("cover_letter_type_text_trace")
    review_screenshot_exists = _path_exists(review_screenshot, base_dir=base_dir)
    cover_letter_trace_exists = _path_exists(cover_letter_trace, base_dir=base_dir)
    filled_answers_have_sources = all(str(field.get("value") or "").strip() for field in answered_question_fields)

    checks = {
        "final_submissions": final_submissions,
        "submit_clicks": submit_clicks,
        "final_submit_guard_v1_required_for_future_submit": True,
        "final_submit_visible_blocker_v1_state": "review_step_detected",
        "application_flow_state": "review_step_detected" if record.get("stage") == "review_before_submit" else str(record.get("stage") or "unknown"),
        "stop_reason": "stopped_before_final_submit" if record.get("stage") == "review_before_submit" else "not_at_review_step",
        "resume_kept": bool(resume_field),
        "cover_letter_filled": bool(cover_letter_field and str(cover_letter_field.get("value") or "").strip()),
        "employer_questions_answered": f"{answered_question_count}/{expected_question_total}",
        "persistent_profile_updates": len(persistent_profile_updates),
        "seek_profile_suggestions_choice": (
            "Don't include"
            if any("Don't include" in value for value in seek_profile_suggestion_choices)
            else ("not_shown" if not seek_profile_suggestions_present else None)
        ),
        "filled_answers_have_evidence_source": filled_answers_have_sources,
        "final_review_screenshot_exists": review_screenshot_exists,
        "cover_letter_trace_exists": cover_letter_trace_exists,
    }
    passed = (
        final_submissions == 0
        and submit_clicks == 0
        and checks["application_flow_state"] == "review_step_detected"
        and checks["resume_kept"] is True
        and checks["cover_letter_filled"] is True
        and answered_question_count == expected_question_total
        and len(persistent_profile_updates) == 0
        and checks["seek_profile_suggestions_choice"] in {"Don't include", "not_shown"}
        and filled_answers_have_sources
        and review_screenshot_exists
        and cover_letter_trace_exists
    )

    return {
        "contract_version": "seek_application_final_review_audit_v1",
        "created_at": created_at,
        "job_id": record.get("job_id"),
        "job_title": record.get("job_title"),
        "apply_url": record.get("apply_url"),
        "record_stage": record.get("stage"),
        "decision": "pass_stopped_before_final_submit" if passed else "needs_review",
        "checks": checks,
        "filled_field_count": len(fields),
        "evidence": evidence,
    }


def _blocked_downstream(*, all_blocked: bool) -> dict[str, bool]:
    return {
        "cover_letter_draft": all_blocked,
        "answer_plan": all_blocked,
        "safe_fill": all_blocked,
        "submit": True,
    }


def _is_seek_profile_suggestion_field(field: dict[str, Any]) -> bool:
    key = _clean_text(str(field.get("field") or "")).casefold()
    return "suggestion" in key or key in {"seek_profile_suggestion", "resume_role_suggestions"}


def _detected_terms(haystack: str, terms: set[str]) -> list[str]:
    return sorted(term for term in terms if term in haystack)


def _current_seek_application_step(items: list[dict[str, Any]]) -> str | None:
    for item in items:
        key = _clean_text(str(item.get("text") or "")).casefold()
        if not key:
            continue
        compact_key = re.sub(r"[^0-9a-z]+", "", key)
        if (
            "/apply/profile" in key
            or "/apply/profil" in key
            or key.startswith("update seek profile | seek")
            or compact_key.startswith("updateseekprofile")
            or compact_key.startswith("updateseekprofle")
        ):
            return "update_seek_profile"
        if "/apply/role-requirements" in key or key.startswith("answer employer questions | seek"):
            return "answer_employer_questions"
        if "/apply/documents" in key or key.startswith("choose documents | seek"):
            return "choose_documents"
        if "/apply/review" in key or key.startswith("review and submit | seek") or key.startswith("review your application | seek"):
            return "review_and_submit"
    return None


def _review_step_is_current(items: list[dict[str, Any]], haystack: str, *, current_step: str | None) -> bool:
    if current_step is not None:
        return current_step == "review_and_submit"
    for item in items:
        text = _clean_text(str(item.get("text") or ""))
        if not text or _is_seek_application_progress_step(text):
            continue
        if _contains_any(text.casefold(), REVIEW_STEP_TERMS):
            return True
    return _contains_any(haystack, REVIEW_STEP_TERMS)


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
    if items:
        return items
    for index, item in enumerate(payload.get("texts") or []):
        if not isinstance(item, dict):
            continue
        text = _clean_text(item.get("text") or item.get("label"))
        if text:
            items.append(
                {
                    "collection": item.get("source") or "observation_texts",
                    "id": item.get("id") or f"observation_text_{index}",
                    "text": text,
                    "role": _clean_text(item.get("role") or item.get("semantic_role") or "text"),
                    "bbox": item.get("bbox"),
                }
            )
    if items:
        return items
    ocr_result = payload.get("ocr_result") if isinstance(payload.get("ocr_result"), dict) else {}
    for index, item in enumerate(ocr_result.get("items") or ocr_result.get("texts") or []):
        if not isinstance(item, dict):
            continue
        text = _clean_text(item.get("text") or item.get("label"))
        if text:
            items.append(
                {
                    "collection": item.get("source") or "ocr_result",
                    "id": item.get("id") or f"ocr_result_text_{index}",
                    "text": text,
                    "role": _clean_text(item.get("role") or "text"),
                    "bbox": item.get("bbox"),
                }
            )
    return items


def _final_submit_visible_blocker(items: list[dict[str, Any]], *, active_flow_started: bool = True) -> dict[str, Any]:
    scoped = scoped_final_submit_visible_blocker(items, active_flow_started=active_flow_started)
    return {
        **scoped,
        "contract_version": "final_submit_visible_blocker_v1",
        "reason": "final_submit_visible_stop_before_submission" if scoped.get("blocked") else "no_final_submit_visible",
    }


def _final_submit_terms_in_text(text: str) -> list[str]:
    key = text.casefold()
    matched: list[str] = []
    for term in FINAL_SUBMIT_TERMS:
        if term == "submit" and "review and submit" in key:
            continue
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


def _is_generic_generated_submit_label(item: dict[str, Any], text: str) -> bool:
    item_id = str(item.get("id") or "").casefold()
    collection = str(item.get("collection") or "").casefold()
    key = _clean_text(text).casefold()
    return collection == "available_actions" and item_id.startswith("action_screen_") and key in {"submit button", "submit"}


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
        if _clean_text(text).casefold().startswith("dear "):
            compact = {
                **compact,
                "text": "Cover letter body",
                "role": "textarea",
                "bbox": _expanded_cover_letter_bbox(item.get("bbox")) if isinstance(item.get("bbox"), dict) else item.get("bbox"),
                "source_text": text,
            }
        if item.get("collection") == "available_actions":
            actions.append(compact)
        if _is_seek_application_progress_step(text):
            continue
        if (
            _contains_any(key, FORM_TERMS | COVER_LETTER_TERMS | SCREENING_QUESTION_TERMS | RISKY_FORM_TERMS)
            or _clean_text(text).casefold().startswith("dear ")
            or "input" in key
            or "textarea" in key
        ):
            fields.append(compact)
    haystack = " ".join(str(item.get("text") or "") for item in items).casefold()
    field_haystack = " ".join(str(item.get("text") or "") for item in fields).casefold()
    return {
        "contract_version": "application_form_inventory_v1",
        "application_form_detected": bool(fields) or _contains_any(haystack, APPLICATION_FLOW_TERMS | FORM_TERMS),
        "cover_letter_field_detected": _contains_any(haystack, COVER_LETTER_TERMS),
        "screening_questions_detected": _contains_any(field_haystack, SCREENING_QUESTION_TERMS),
        "field_count": len(fields),
        "action_count": len(actions),
        "fields": fields[:40],
        "actions": actions[:40],
    }


def _is_seek_application_progress_step(text: str | None) -> bool:
    key = _clean_text(str(text or "")).casefold()
    return key in {"choose documents", "answer employer questions", "update seek profile", "review and submit"}


def _form_fields_contain_any(form_inventory: dict[str, Any], terms: set[str]) -> bool:
    fields = form_inventory.get("fields") if isinstance(form_inventory, dict) else []
    cover_letter_bboxes = _cover_letter_body_bboxes(fields)
    risk_labels: list[str] = []
    for item in fields:
        if not isinstance(item, dict):
            continue
        text = _clean_text(str(item.get("text") or ""))
        if not text:
            continue
        lowered = text.casefold()
        if len(text) > 240 or lowered.startswith("dear ") or _is_inside_any_bbox(item.get("bbox"), cover_letter_bboxes):
            continue
        risk_labels.append(text)
    haystack = " ".join(risk_labels).casefold()
    return _contains_any(haystack, terms)


def _cover_letter_body_bboxes(fields: list[Any]) -> list[dict[str, Any]]:
    bboxes: list[dict[str, Any]] = []
    for item in fields:
        if not isinstance(item, dict):
            continue
        text = _clean_text(str(item.get("text") or "")).casefold()
        role = _clean_text(str(item.get("role") or "")).casefold()
        bbox = item.get("bbox")
        if not isinstance(bbox, dict):
            continue
        is_cover_letter_container = "cover letter" in text and any(term in role for term in ("group", "input", "textarea", "textbox"))
        is_existing_cover_letter_text = text.startswith("dear ")
        if is_cover_letter_container or is_existing_cover_letter_text:
            bboxes.append(_expanded_cover_letter_bbox(bbox) if is_existing_cover_letter_text else bbox)
    return bboxes


def _expanded_cover_letter_bbox(bbox: dict[str, Any]) -> dict[str, Any]:
    try:
        x = float(bbox.get("x"))
        y = float(bbox.get("y"))
        w = float(bbox.get("w"))
        h = float(bbox.get("h"))
    except (TypeError, ValueError):
        return bbox
    return {
        "x": max(0, int(round(x - 40))),
        "y": max(0, int(round(y - 20))),
        "w": int(round(max(w + 120, 760))),
        "h": int(round(max(h, 360))),
    }


def _is_inside_any_bbox(candidate: Any, containers: list[dict[str, Any]]) -> bool:
    if not isinstance(candidate, dict) or not containers:
        return False
    try:
        x = float(candidate.get("x"))
        y = float(candidate.get("y"))
        w = float(candidate.get("w"))
        h = float(candidate.get("h"))
    except (TypeError, ValueError):
        return False
    if w <= 0 or h <= 0:
        return False
    cx = x + w / 2
    cy = y + h / 2
    for bbox in containers:
        try:
            bx = float(bbox.get("x"))
            by = float(bbox.get("y"))
            bw = float(bbox.get("w"))
            bh = float(bbox.get("h"))
        except (TypeError, ValueError):
            continue
        if bx <= cx <= bx + bw and by <= cy <= by + bh:
            return True
    return False


def _upload_required(haystack: str) -> bool:
    if not _contains_any(haystack, UPLOAD_TERMS):
        return False
    resume_upload_visible = any(term in haystack for term in ("upload resume", "upload a resume", "upload cv", "upload a cv", "attach resume", "attach cv"))
    resume_already_attached = "resume attached" in haystack or "resumé attached" in haystack or re.search(r"\b[\w.-]+\\.pdf\b", haystack)
    if resume_upload_visible:
        return not bool(resume_already_attached)
    if "upload a cover letter" in haystack or "upload cover letter" in haystack or "attach cover letter" in haystack:
        return False
    return True


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _contains_any(haystack: str, terms: set[str]) -> bool:
    return any(term in haystack for term in terms)


def _path_exists(value: Any, *, base_dir: Path | str | None = None) -> bool:
    if not str(value or "").strip():
        return False
    path = Path(str(value))
    if not path.is_absolute() and base_dir is not None:
        path = Path(base_dir) / path
    return path.exists()
