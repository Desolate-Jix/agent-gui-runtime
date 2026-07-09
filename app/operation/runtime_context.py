from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class OperationRuntimeContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    contract_version: Literal["operation_runtime_context_v1"] = "operation_runtime_context_v1"
    authorized_intent_id: str | None = None
    semantic_action: str | None = None
    skill_id: str | None = None
    gate_decision_id: str | None = None
    gate_policy_version: str | None = None
    allowed_action_scope: str | None = None
    capture_id: str | None = None
    window_binding_id: str | None = None
    viewport_size: dict[str, int] | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    source: str = "request_or_runtime"
    synthesized_fields: list[str] = Field(default_factory=list)


def build_operation_runtime_context(
    *,
    request: Any,
    skill_id: str,
    semantic_action: str,
    side_effect_class: Literal["read_only", "navigation", "write", "dangerous"] = "read_only",
    requires_gate: bool,
    gate_decision: dict[str, Any] | None = None,
    capture_id: str | None = None,
    window_binding_id: str | None = None,
    viewport_size: dict[str, int] | None = None,
    allowed_action_scope: str | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    raw = _context_payload(request)
    metadata = getattr(request, "metadata", None)
    if isinstance(metadata, dict):
        nested = metadata.get("operation_context") or metadata.get("operation_runtime_context")
        if isinstance(nested, dict):
            raw = {**nested, **raw}

    synthesized: list[str] = list(raw.get("synthesized_fields") or [])
    goal_text = _request_text(request)
    authorized_intent_id = _first_text(raw.get("authorized_intent_id"), _metadata_text(metadata, "authorized_intent_id"))
    if not authorized_intent_id:
        authorized_intent_id = _stable_id("intent", skill_id, semantic_action, goal_text)
        synthesized.append("authorized_intent_id")

    gate_decision_id = _first_text(raw.get("gate_decision_id"), _metadata_text(metadata, "gate_decision_id"))
    gate_policy_version = _first_text(raw.get("gate_policy_version"), _metadata_text(metadata, "gate_policy_version"))
    scope = _first_text(raw.get("allowed_action_scope"), allowed_action_scope, _metadata_text(metadata, "allowed_action_scope"))
    if requires_gate and not gate_decision_id:
        gate_decision_id = _stable_id("gate", skill_id, semantic_action, gate_decision or {}, goal_text)
        synthesized.append("gate_decision_id")
    if requires_gate and not gate_policy_version:
        gate_policy_version = _gate_policy_from_decision(gate_decision) or "runtime_gate_policy_v1"
        synthesized.append("gate_policy_version")
    if requires_gate and not scope:
        scope = _scope_for_side_effect(side_effect_class, semantic_action)
        synthesized.append("allowed_action_scope")

    resolved_capture_id = _first_text(raw.get("capture_id"), capture_id, _metadata_text(metadata, "capture_id"))
    if not resolved_capture_id:
        resolved_capture_id = _capture_id_from_request(request)
        if resolved_capture_id:
            synthesized.append("capture_id")

    resolved_window_binding_id = _first_text(
        raw.get("window_binding_id"),
        window_binding_id,
        _metadata_text(metadata, "window_binding_id"),
    )
    if not resolved_window_binding_id:
        resolved_window_binding_id = _window_binding_id_from_request(request)
        if resolved_window_binding_id:
            synthesized.append("window_binding_id")

    resolved_viewport_size = _dict_or_none(raw.get("viewport_size")) or viewport_size or _viewport_size_from_request(request)
    if resolved_viewport_size and raw.get("viewport_size") is None and viewport_size is None:
        synthesized.append("viewport_size")

    refs = _list_text(raw.get("evidence_refs"))
    refs.extend(evidence_refs or [])
    refs = _dedupe_text(refs)

    context = OperationRuntimeContext(
        authorized_intent_id=authorized_intent_id,
        semantic_action=_first_text(raw.get("semantic_action"), semantic_action),
        skill_id=_first_text(raw.get("skill_id"), skill_id),
        gate_decision_id=gate_decision_id,
        gate_policy_version=gate_policy_version,
        allowed_action_scope=scope,
        capture_id=resolved_capture_id,
        window_binding_id=resolved_window_binding_id,
        viewport_size=resolved_viewport_size,
        evidence_refs=refs,
        source="request_or_runtime",
        synthesized_fields=_dedupe_text(synthesized),
    ).model_dump()
    context["side_effect_class"] = side_effect_class
    context["requires_gate"] = requires_gate
    context["validation"] = validate_operation_runtime_context(context)
    return context


def operation_trace_link(
    context: dict[str, Any],
    *,
    result_status: str,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    refs = _dedupe_text([*context.get("evidence_refs", []), *(evidence_refs or [])])
    return {
        "contract_version": "operation_trace_link_v1",
        "authorized_intent_id": context.get("authorized_intent_id"),
        "semantic_action": context.get("semantic_action"),
        "skill_id": context.get("skill_id"),
        "gate_decision_id": context.get("gate_decision_id"),
        "capture_id": context.get("capture_id"),
        "window_binding_id": context.get("window_binding_id"),
        "evidence_refs": refs,
        "result_status": result_status,
    }


def validate_operation_runtime_context(context: dict[str, Any]) -> dict[str, Any]:
    required = ["authorized_intent_id", "semantic_action", "skill_id"]
    if context.get("requires_gate"):
        required.extend(["gate_decision_id", "gate_policy_version", "allowed_action_scope"])
    side_effect = context.get("side_effect_class")
    if side_effect in {"navigation", "write", "dangerous"}:
        required.append("window_binding_id")
    missing = [field for field in required if not context.get(field)]
    return {
        "contract_version": "operation_runtime_context_validation_v1",
        "status": "pass" if not missing else "warning",
        "missing_fields": missing,
        "requires_gate": bool(context.get("requires_gate")),
        "side_effect_class": side_effect,
    }


def _context_payload(request: Any) -> dict[str, Any]:
    value = getattr(request, "operation_context", None)
    if value is None:
        return {}
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=True)
    if isinstance(value, dict):
        return dict(value)
    return {}


def _request_text(request: Any) -> str:
    for name in ("goal", "task", "reason", "expected_change", "target_container_id", "app_id"):
        value = getattr(request, name, None)
        if isinstance(value, str) and value:
            return value
    return request.__class__.__name__


def _metadata_text(metadata: Any, key: str) -> str | None:
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(_stable_repr(part) for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _stable_repr(value: Any) -> str:
    if isinstance(value, dict):
        return repr(sorted((str(k), _stable_repr(v)) for k, v in value.items()))
    if isinstance(value, list):
        return repr([_stable_repr(item) for item in value])
    return str(value)


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _dict_or_none(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    width = value.get("width")
    height = value.get("height")
    if isinstance(width, int) and isinstance(height, int):
        return {"width": width, "height": height}
    return None


def _list_text(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _gate_policy_from_decision(gate_decision: dict[str, Any] | None) -> str | None:
    if not isinstance(gate_decision, dict):
        return None
    for key in ("gate_policy_version", "policy_version", "contract_version"):
        value = gate_decision.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _scope_for_side_effect(side_effect_class: str, semantic_action: str) -> str:
    if semantic_action == "open_apply_flow":
        return "active_job_detail_apply_entry"
    if side_effect_class == "write":
        return "verified_field_only"
    if side_effect_class == "navigation":
        return "bound_window_current_capture"
    if side_effect_class == "dangerous":
        return "explicit_user_authorized_dangerous_action"
    return "read_only"


def _capture_id_from_request(request: Any) -> str | None:
    for name in ("observe_trace_path", "image_path", "before_image", "after_image", "source_trace_path"):
        value = getattr(request, name, None)
        if isinstance(value, str) and value:
            return _stable_id("capture", value)
    return None


def _window_binding_id_from_request(request: Any) -> str | None:
    metadata = getattr(request, "metadata", None)
    if isinstance(metadata, dict):
        bound_window = metadata.get("bound_window")
        if isinstance(bound_window, dict):
            handle = bound_window.get("handle")
            if handle is not None:
                return f"window:{handle}"
    return None


def _viewport_size_from_request(request: Any) -> dict[str, int] | None:
    value = getattr(request, "coordinate_window_size", None)
    return _dict_or_none(value)
