from __future__ import annotations

from typing import Any


CONTRACT_VERSION = "form_question_contract_v1"


def build_form_question_contract(item: dict[str, Any] | None) -> dict[str, Any]:
    payload = item if isinstance(item, dict) else {}
    question_id = _clean(payload.get("question_id") or payload.get("field_id") or payload.get("action_id") or payload.get("id"))
    label = _clean(payload.get("label") or payload.get("text") or payload.get("question_text"))
    field_type = _clean(
        "action"
        if payload.get("action_type")
        else payload.get("field_type") or payload.get("type") or payload.get("role")
    ).casefold()
    capture_id = _clean(
        payload.get("capture_id")
        or (payload.get("evidence") or {}).get("capture_id")
        if isinstance(payload.get("evidence"), dict)
        else payload.get("capture_id")
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "question_id": question_id,
        "label": label,
        "field_type": field_type or "unknown",
        "required": bool(payload.get("required")),
        "disabled": bool(payload.get("disabled")),
        "risk": _clean(payload.get("risk") or payload.get("risk_class")) or "ordinary_field",
        "options": [_option_contract(option) for option in payload.get("options") or [] if isinstance(option, dict)],
        "source_capture_id": capture_id or None,
    }


def _option_contract(option: dict[str, Any]) -> dict[str, Any]:
    return {
        "option_id": _clean(option.get("option_id") or option.get("control_id") or option.get("id")),
        "label": _clean(option.get("label") or option.get("text")),
        "disabled": bool(option.get("disabled")),
    }


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())
