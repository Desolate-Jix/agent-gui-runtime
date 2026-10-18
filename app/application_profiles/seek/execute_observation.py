from __future__ import annotations

from typing import Any


CONTRACT_VERSION = "execute_observation_v1"

FINAL_SUBMIT_TERMS = ("submit application", "send application", "complete application", "finish application")
CONTINUE_TERMS = ("continue", "save and continue", "next", "review")
PROFILE_MUTATION_TERMS = ("add ", "edit", "add role", "add education", "add skills", "add licence")


def build_seek_execute_observation(
    observation: dict[str, Any] | None = None,
    *,
    application_flow_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize a SEEK execution page into agent-consumable state without a model call."""

    flow = application_flow_state if isinstance(application_flow_state, dict) else {}
    items = _collect_items(observation, flow)
    texts = [str(item.get("text") or item.get("label") or "").strip() for item in items]
    haystack = " ".join(texts).casefold()
    page_state = _page_state(flow, haystack)
    primary_actions = _actions(items, CONTINUE_TERMS)
    danger_actions = _actions(items, FINAL_SUBMIT_TERMS)
    profile_mutation_actions = _actions(items, PROFILE_MUTATION_TERMS)
    safety_blockers: list[dict[str, Any]] = []
    if danger_actions:
        safety_blockers.append(
            {
                "kind": "final_submit_visible",
                "reason": "Submit-like action is visible and remains forbidden without explicit user approval.",
                "actions": danger_actions,
            }
        )
    if page_state == "profile_prompt" and profile_mutation_actions:
        safety_blockers.append(
            {
                "kind": "profile_mutation_actions_visible",
                "reason": "Add/Edit profile controls are visible; continue only without persistent profile edits.",
                "actions": profile_mutation_actions,
            }
        )

    return {
        "contract_version": CONTRACT_VERSION,
        "page_state": page_state,
        "state_confidence": _confidence(page_state, flow, texts),
        "current_step": flow.get("current_step"),
        "source_state_type": flow.get("state_type"),
        "evidence": _evidence(texts, page_state),
        "regions": [],
        "primary_actions": primary_actions,
        "danger_actions": danger_actions,
        "profile_mutation_actions": profile_mutation_actions,
        "available_actions": _available_actions(items),
        "form_fields_hint": _form_fields(items),
        "safety_blockers": safety_blockers,
        "trace_path": (observation or {}).get("trace_path") if isinstance(observation, dict) else None,
    }


def _page_state(flow: dict[str, Any], haystack: str) -> str:
    step = str(flow.get("current_step") or "").casefold()
    state_type = str(flow.get("state_type") or "").casefold()
    if step == "review_and_submit" or state_type in {"final_submit_visible", "review_step_detected"} or "review and submit" in haystack:
        return "review_before_submit"
    if step == "update_seek_profile" or "update seek profile" in haystack:
        return "profile_prompt"
    if step == "answer_employer_questions" or "employer questions" in haystack or "required field" in haystack:
        return "questionnaire"
    if step == "choose_documents" or "choose documents" in haystack or "resume attached" in haystack:
        return "choose_documents"
    if "apply" in haystack and "sandfield" in haystack:
        return "application_entry"
    return "unknown"


def _confidence(page_state: str, flow: dict[str, Any], texts: list[str]) -> float:
    if page_state == "unknown":
        return 0.2 if texts else 0.0
    if flow.get("current_step") or flow.get("state_type"):
        return 0.9
    return 0.72


def _collect_items(observation: dict[str, Any] | None, flow: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    inventory = flow.get("application_form_inventory") if isinstance(flow.get("application_form_inventory"), dict) else {}
    for key in ("fields", "actions"):
        values = inventory.get(key)
        if isinstance(values, list):
            items.extend(item for item in values if isinstance(item, dict))
    evidence = flow.get("evidence") if isinstance(flow.get("evidence"), dict) else {}
    for text in evidence.get("texts") or []:
        if str(text or "").strip():
            items.append({"text": str(text), "role": "text", "source": "flow_state_evidence"})
    payload = observation if isinstance(observation, dict) else {}
    screen_reading = payload.get("screen_reading") if isinstance(payload.get("screen_reading"), dict) else {}
    for key in ("ui_elements", "elements", "actions"):
        values = screen_reading.get(key)
        if isinstance(values, list):
            items.extend(item for item in values if isinstance(item, dict))
    return items


def _actions(items: list[dict[str, Any]], terms: tuple[str, ...]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        text = str(item.get("text") or item.get("label") or "").strip()
        lowered = text.casefold()
        if text and any(term in lowered for term in terms):
            out.append(_compact_item(item, text=text))
    return _dedupe(out)


def _available_actions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        role = str(item.get("role") or "").casefold()
        text = str(item.get("text") or item.get("label") or "").strip()
        if role in {"button", "link", "input", "textbox", "radio", "checkbox", "textarea"} or text.casefold() in {"continue", "back"}:
            out.append(_compact_item(item, text=text))
    return _dedupe(out)[:80]


def _form_fields(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for item in items:
        role = str(item.get("role") or "").casefold()
        text = str(item.get("text") or item.get("label") or "").strip()
        if role in {"input", "textbox", "textarea", "radio", "checkbox"} or "required field" in text.casefold():
            fields.append(_compact_item(item, text=text))
    return _dedupe(fields)[:80]


def _compact_item(item: dict[str, Any], *, text: str) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "text": text[:240],
        "role": item.get("role"),
        "bbox": item.get("bbox"),
        "source": item.get("collection") or item.get("source"),
    }


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = (str(item.get("text")), str(item.get("role")), str(item.get("bbox")))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _evidence(texts: list[str], page_state: str) -> list[dict[str, str]]:
    terms = {
        "review_before_submit": ("review and submit", "submit application", "documents included"),
        "profile_prompt": ("update seek profile", "add skills", "career history"),
        "questionnaire": ("employer questions", "required field", "yes"),
        "choose_documents": ("choose documents", "resume", "cover letter"),
    }.get(page_state, ())
    evidence: list[dict[str, str]] = []
    for text in texts:
        lowered = text.casefold()
        if any(term in lowered for term in terms):
            evidence.append({"text": text[:240], "matched_state": page_state})
        if len(evidence) >= 12:
            break
    return evidence
