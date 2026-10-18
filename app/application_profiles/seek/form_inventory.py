from __future__ import annotations

from typing import Any

from app.operation.form_inventory import build_form_question_inventory


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

    capture_id = _capture_id(flow)
    fields = [*_cover_letter_fields(app_inventory, capture_id=capture_id), *_planned_answer_fields(answer_plan, capture_id=capture_id)]
    questions = _question_fields(question_inventory, capture_id=capture_id)
    actions = _action_items(app_inventory, capture_id=capture_id)

    return build_form_question_inventory(
        form_state=str(flow.get("current_step") or flow.get("state_type") or "unknown"),
        current_capture_id=capture_id,
        active_scope_bbox=_active_scope_bbox(flow, app_inventory),
        fields=fields,
        questions=questions,
        actions=actions,
        source_contracts={
            "application_flow_state": flow.get("contract_version"),
            "employer_question_inventory": question_inventory.get("contract_version"),
            "application_answer_plan": answer_plan.get("contract_version"),
        },
    )


def _cover_letter_fields(app_inventory: dict[str, Any], *, capture_id: str) -> list[dict[str, Any]]:
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
                    "capture_id": item.get("capture_id") or capture_id,
                }
            )
    return out


def _question_fields(question_inventory: dict[str, Any], *, capture_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for question in question_inventory.get("questions") or []:
        if not isinstance(question, dict):
            continue
        controls = []
        for control in question.get("control_candidates") or []:
            if isinstance(control, dict):
                controls.append({**control, "capture_id": control.get("capture_id") or capture_id})
        out.append({
            **question,
            "field_id": question.get("question_id"),
            "label": question.get("question_text"),
            "field_type": question.get("answer_type") or "unknown",
            "label_bbox": question.get("question_bbox"),
            "group_bbox": question.get("question_group_bbox") or question.get("group_bbox"),
            "control_candidates": controls,
            "required": True,
            "answer_source_required": True,
            "source": "employer_question_inventory_v1",
            "capture_id": question.get("capture_id") or capture_id,
        })
    return out


def _planned_answer_fields(answer_plan: dict[str, Any], *, capture_id: str) -> list[dict[str, Any]]:
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
                "capture_id": source.get("capture_id") or capture_id,
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


def _action_items(app_inventory: dict[str, Any], *, capture_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in _items(app_inventory):
        role = str(item.get("role") or "").casefold()
        if role in {"button", "link", "action"} or item.get("collection") == "available_actions":
            out.append({**item, "capture_id": item.get("capture_id") or capture_id})
    return _dedupe_actions(out)


def _capture_id(flow: dict[str, Any]) -> str:
    freshness = flow.get("candidate_freshness") if isinstance(flow.get("candidate_freshness"), dict) else {}
    evidence = flow.get("evidence") if isinstance(flow.get("evidence"), dict) else {}
    return str(flow.get("capture_id") or freshness.get("capture_id") or evidence.get("capture_id") or "").strip()


def _active_scope_bbox(flow: dict[str, Any], app_inventory: dict[str, Any]) -> dict[str, Any] | None:
    for value in (
        flow.get("active_form_bbox"),
        flow.get("active_modal_bbox"),
        flow.get("form_bbox"),
        app_inventory.get("scope_bbox"),
    ):
        if isinstance(value, dict):
            return value
    return None


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
