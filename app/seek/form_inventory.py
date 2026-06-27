from __future__ import annotations

from typing import Any


CONTRACT_VERSION = "form_field_inventory_v1"


def build_seek_form_field_inventory(
    application_flow_state: dict[str, Any] | None,
    *,
    employer_question_inventory: dict[str, Any] | None = None,
    application_answer_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Expose SEEK application fields as a stable fill-first inventory."""

    flow = application_flow_state if isinstance(application_flow_state, dict) else {}
    app_inventory = flow.get("application_form_inventory") if isinstance(flow.get("application_form_inventory"), dict) else {}
    question_inventory = employer_question_inventory if isinstance(employer_question_inventory, dict) else {}
    answer_plan = application_answer_plan if isinstance(application_answer_plan, dict) else {}

    fields: list[dict[str, Any]] = []
    fields.extend(_cover_letter_fields(app_inventory))
    fields.extend(_question_fields(question_inventory))
    fields.extend(_planned_answer_fields(answer_plan))

    return {
        "contract_version": CONTRACT_VERSION,
        "form_state": flow.get("current_step") or flow.get("state_type") or "unknown",
        "fields": _dedupe_fields(fields),
        "continue_action": _first_action(app_inventory, ("continue", "save and continue", "next", "review")),
        "danger_actions": _actions(app_inventory, ("submit application", "send application", "complete application", "finish application")),
        "profile_mutation_actions": _actions(app_inventory, ("add ", "edit", "add role", "add education", "add skills")),
        "source_contracts": {
            "application_flow_state": flow.get("contract_version"),
            "employer_question_inventory": question_inventory.get("contract_version"),
            "application_answer_plan": answer_plan.get("contract_version"),
        },
    }


def _cover_letter_fields(app_inventory: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in _items(app_inventory):
        text = str(item.get("text") or item.get("label") or "").strip()
        role = str(item.get("role") or "").casefold()
        lowered = text.casefold()
        if "cover letter" in lowered or role == "textarea":
            out.append(
                {
                    "field_id": "cover_letter" if "cover letter" in lowered or role == "textarea" else item.get("id"),
                    "label": "Cover letter body" if role == "textarea" else text or "Cover letter",
                    "field_type": "textarea" if role == "textarea" else role or "group",
                    "field_bbox": item.get("bbox"),
                    "required": False,
                    "answer_source_required": True,
                    "source": item.get("collection") or "application_form_inventory",
                    "source_id": item.get("id"),
                }
            )
    return out


def _question_fields(question_inventory: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for question in question_inventory.get("questions") or []:
        if not isinstance(question, dict):
            continue
        out.append(
            {
                "field_id": question.get("question_id"),
                "label": question.get("question_text"),
                "field_type": question.get("answer_type") or "unknown",
                "label_bbox": question.get("question_bbox"),
                "group_bbox": question.get("group_bbox"),
                "control_candidates": question.get("control_candidates") or [],
                "required": True,
                "answer_source_required": True,
                "source": "employer_question_inventory_v1",
            }
        )
    return out


def _planned_answer_fields(answer_plan: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in answer_plan.get("planned_answers") or []:
        if not isinstance(item, dict):
            continue
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        out.append(
            {
                "field_id": source.get("id") or item.get("label"),
                "label": item.get("label"),
                "field_type": source.get("role") or "unknown",
                "field_bbox": source.get("bbox"),
                "required": False,
                "answer_source_required": item.get("answer_source") is not None,
                "answer_source": item.get("answer_source"),
                "category": item.get("category"),
                "source": "application_answer_plan_v1",
            }
        )
    return out


def _items(app_inventory: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in ("fields", "actions"):
        values = app_inventory.get(key)
        if isinstance(values, list):
            out.extend(item for item in values if isinstance(item, dict))
    return out


def _actions(app_inventory: dict[str, Any], terms: tuple[str, ...]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in _items(app_inventory):
        text = str(item.get("text") or item.get("label") or "").strip()
        if text and any(term in text.casefold() for term in terms):
            out.append({"id": item.get("id"), "text": text, "role": item.get("role"), "bbox": item.get("bbox")})
    return _dedupe_actions(out)


def _first_action(app_inventory: dict[str, Any], terms: tuple[str, ...]) -> dict[str, Any] | None:
    actions = _actions(app_inventory, terms)
    return actions[0] if actions else None


def _dedupe_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for field in fields:
        key = (str(field.get("field_id")), str(field.get("label")), str(field.get("field_bbox") or field.get("group_bbox")))
        if key in seen:
            continue
        seen.add(key)
        out.append(field)
    return out


def _dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for action in actions:
        key = (str(action.get("text")), str(action.get("bbox")))
        if key in seen:
            continue
        seen.add(key)
        out.append(action)
    return out
