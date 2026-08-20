from __future__ import annotations

from typing import Any


CONTRACT_VERSION = "form_question_inventory_v1"
FINAL_ACTION_TERMS = (
    "submit application",
    "send application",
    "complete application",
    "finish application",
    "review and submit",
    "confirm application",
    "payment",
    "purchase",
)
CONTINUE_ACTION_TERMS = ("continue", "save and continue", "next", "review")
PROFILE_MUTATION_TERMS = ("add ", "edit", "upload", "replace", "update profile")


def build_form_question_inventory(
    *,
    form_state: str,
    current_capture_id: str | None,
    active_scope_bbox: dict[str, Any] | None,
    fields: list[dict[str, Any]] | None = None,
    questions: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    source_contracts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    capture_id = _text(current_capture_id)
    scope_bbox = _bbox(active_scope_bbox)
    valid_fields: list[dict[str, Any]] = []
    valid_questions: list[dict[str, Any]] = []
    invalid_fields: list[dict[str, Any]] = []
    excluded_outside_scope_count = 0

    for item in fields or []:
        if not isinstance(item, dict):
            continue
        validity = _capture_validity(item, capture_id)
        if validity:
            invalid_fields.append(_invalid_item(item, validity))
            continue
        bbox = _bbox(item.get("field_bbox") or item.get("bbox"))
        if scope_bbox and bbox and not _center_inside(bbox, scope_bbox):
            excluded_outside_scope_count += 1
            continue
        valid_fields.append(_normalized_field(item, bbox=bbox))

    for question in questions or []:
        if not isinstance(question, dict):
            continue
        validity = _capture_validity(question, capture_id)
        if validity:
            invalid_fields.append(_invalid_item(question, validity))
            continue
        group_bbox = _bbox(
            question.get("question_group_bbox")
            or question.get("group_bbox")
            or question.get("question_bbox")
            or question.get("bbox")
        )
        if scope_bbox and group_bbox and not _center_inside(group_bbox, scope_bbox):
            excluded_outside_scope_count += 1
            continue
        normalized, invalid_controls = _normalized_question(
            question,
            group_bbox=group_bbox,
            current_capture_id=capture_id,
        )
        valid_questions.append(normalized)
        invalid_fields.extend(invalid_controls)

    normalized_actions: list[dict[str, Any]] = []
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        validity = _capture_validity(action, capture_id)
        if validity:
            invalid_fields.append(_invalid_item(action, validity))
            continue
        bbox = _bbox(action.get("bbox"))
        if scope_bbox and bbox and not _center_inside(bbox, scope_bbox):
            excluded_outside_scope_count += 1
            continue
        normalized_actions.append(_normalized_action(action, bbox=bbox))

    normalized_actions = _dedupe(normalized_actions, key_fields=("action_id", "text", "bbox"))
    danger_actions = [item for item in normalized_actions if item["action_type"] == "final_action"]
    continue_action = next(
        (
            item
            for item in normalized_actions
            if item["action_type"] == "continue_action"
        ),
        None,
    )

    all_fields = _dedupe(
        [*valid_fields, *valid_questions],
        key_fields=("field_id", "label", "field_bbox", "group_bbox"),
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "compatibility_contracts": ["form_field_inventory_v1"],
        "form_state": _text(form_state) or "unknown",
        "capture_id": capture_id or None,
        "active_scope_bbox": scope_bbox,
        "questions": valid_questions,
        "fields": all_fields,
        "continue_action": continue_action,
        "danger_actions": danger_actions,
        "profile_mutation_actions": [
            item
            for item in normalized_actions
            if any(term in item["text"].casefold() for term in PROFILE_MUTATION_TERMS)
        ],
        "invalid_fields": _dedupe(invalid_fields, key_fields=("field_id", "invalid_reason")),
        "excluded_outside_scope_count": excluded_outside_scope_count,
        "source_contracts": dict(source_contracts or {}),
        "artifact_is_authorization": False,
        "fill_attempted": False,
        "submit_attempted": False,
    }


def _normalized_field(item: dict[str, Any], *, bbox: dict[str, int] | None) -> dict[str, Any]:
    label = _text(item.get("label") or item.get("text"))
    field_type = _field_type(item)
    disabled = bool(item.get("disabled")) or item.get("enabled") is False
    return {
        "field_id": item.get("field_id") or item.get("id") or label,
        "label": label,
        "field_type": field_type,
        "field_bbox": bbox,
        "required": bool(item.get("required", False)),
        "disabled": disabled,
        "risk_class": "unsupported_file_upload" if field_type == "file_upload" else "disabled" if disabled else "ordinary_field",
        "answer_source_required": bool(item.get("answer_source_required", True)),
        "source": item.get("source") or item.get("collection") or "form_evidence",
        "source_id": item.get("source_id") or item.get("id"),
        "capture_id": _text(item.get("capture_id")) or None,
    }


def _normalized_question(
    question: dict[str, Any],
    *,
    group_bbox: dict[str, int] | None,
    current_capture_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    options: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    question_id = question.get("field_id") or question.get("question_id") or question.get("id")
    for control in question.get("control_candidates") or []:
        if not isinstance(control, dict):
            continue
        validity = _capture_validity(control, current_capture_id)
        if validity:
            invalid.append(_invalid_item(control, validity))
            continue
        bbox = _bbox(control.get("bbox"))
        explicit_owner = _text(control.get("question_id"))
        if explicit_owner and explicit_owner != _text(question_id):
            continue
        if not explicit_owner and group_bbox and bbox and not _center_inside(bbox, group_bbox):
            continue
        options.append(
            {
                "control_id": control.get("control_id") or control.get("id"),
                "label": _text(control.get("label") or control.get("text")),
                "control_type": _field_type(control),
                "bbox": bbox,
                "disabled": bool(control.get("disabled")) or control.get("enabled") is False,
                "capture_id": _text(control.get("capture_id")) or None,
            }
        )
    field_type = _canonical_type(question.get("field_type") or question.get("answer_type") or question.get("role"))
    if field_type == "unknown" and options:
        field_type = options[0]["control_type"]
    return (
        {
            "field_id": question_id,
            "label": _text(question.get("label") or question.get("question_text") or question.get("text")),
            "field_type": field_type,
            "label_bbox": _bbox(question.get("label_bbox") or question.get("question_bbox")),
            "group_bbox": group_bbox,
            "options": _dedupe(options, key_fields=("control_id", "bbox")),
            "control_candidates": _dedupe(options, key_fields=("control_id", "bbox")),
            "required": bool(question.get("required", True)),
            "disabled": bool(question.get("disabled")) or question.get("enabled") is False,
            "risk_class": "ordinary_question",
            "answer_source_required": bool(question.get("answer_source_required", True)),
            "source": question.get("source") or "question_inventory",
            "capture_id": _text(question.get("capture_id")) or None,
        },
        invalid,
    )


def _normalized_action(item: dict[str, Any], *, bbox: dict[str, int] | None) -> dict[str, Any]:
    text = _text(item.get("text") or item.get("label"))
    lowered = text.casefold()
    if any(term in lowered for term in FINAL_ACTION_TERMS):
        action_type = "final_action"
        risk_class = "final_submit"
    elif any(term in lowered for term in CONTINUE_ACTION_TERMS):
        action_type = "continue_action"
        risk_class = "low_risk_navigation"
    else:
        action_type = "form_action"
        risk_class = "needs_review"
    return {
        "action_id": item.get("action_id") or item.get("id"),
        "text": text,
        "role": item.get("role"),
        "bbox": bbox,
        "action_type": action_type,
        "risk_class": risk_class,
        "capture_id": _text(item.get("capture_id")) or None,
    }


def _capture_validity(item: dict[str, Any], current_capture_id: str) -> str | None:
    item_capture_id = _text(item.get("capture_id"))
    if not current_capture_id or not item_capture_id:
        return "missing_capture_id"
    if item_capture_id != current_capture_id:
        return "stale_capture"
    return None


def _invalid_item(item: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "field_id": item.get("field_id") or item.get("question_id") or item.get("control_id") or item.get("id"),
        "label": _text(item.get("label") or item.get("question_text") or item.get("text")),
        "invalid_reason": reason,
        "capture_id": _text(item.get("capture_id")) or None,
    }


def _field_type(item: dict[str, Any]) -> str:
    input_type = _text(item.get("input_type") or item.get("type")).casefold()
    role = _text(item.get("field_type") or item.get("answer_type") or item.get("role")).casefold()
    if input_type in {"email", "tel", "phone", "file"}:
        return _canonical_type(input_type)
    return _canonical_type(role)


def _canonical_type(value: Any) -> str:
    key = _text(value).casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "input": "text",
        "textbox": "text",
        "text_input": "text",
        "text": "text",
        "email": "email",
        "tel": "phone",
        "telephone": "phone",
        "phone": "phone",
        "textarea": "textarea",
        "multiline": "textarea",
        "radio": "radio",
        "radio_button": "radio",
        "checkbox": "checkbox",
        "combobox": "select",
        "listbox": "select",
        "select": "select",
        "dropdown": "select",
        "file": "file_upload",
        "file_input": "file_upload",
        "file_upload": "file_upload",
    }
    return aliases.get(key, key or "unknown")


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        x = int(value.get("x", value.get("left")))
        y = int(value.get("y", value.get("top")))
        w = int(value.get("w", value.get("width")))
        h = int(value.get("h", value.get("height")))
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def _center_inside(inner: dict[str, int], outer: dict[str, int]) -> bool:
    center_x = inner["x"] + inner["w"] / 2
    center_y = inner["y"] + inner["h"] / 2
    return (
        outer["x"] <= center_x <= outer["x"] + outer["w"]
        and outer["y"] <= center_y <= outer["y"] + outer["h"]
    )


def _dedupe(items: list[dict[str, Any]], *, key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = "|".join(str(item.get(field)) for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())
