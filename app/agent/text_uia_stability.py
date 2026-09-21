"""填写保持既有字段身份与引用，复用公共只读 UIA 上下文比较。"""
from __future__ import annotations

from app.agent.control_uia_stability import _compare_uia_context
from app.agent.text_field_evidence import TextFieldIdentity


def compare_fill_uia_context(*, field_identity, original_evidence, original_uia,
                             current_evidence, current_uia) -> dict | None:
    """保留旧的字段引用结构、摘要及严格相等行为。"""
    if type(field_identity) is not TextFieldIdentity:
        raise TypeError("text UIA stability requires a typed field identity")
    identity = TextFieldIdentity(**{**field_identity.to_reference(), "runtime_id": tuple(field_identity.runtime_id),
        "window_rect": tuple(field_identity.window_rect), "control_bbox": tuple(field_identity.control_bbox)})
    try:
        result = _compare_uia_context(identity=identity, original_evidence=original_evidence,
            original_uia=original_uia, current_evidence=current_evidence, current_uia=current_uia)
    except ValueError as exc:
        prefix = "control UIA stability: "
        if str(exc).startswith(prefix):
            raise ValueError("text UIA stability: " + str(exc)[len(prefix):]) from None
        raise
    if result is None:
        return None
    return {"contract_version": "text_uia_stability_reference_v1", "policy": "fill_field_uia_context_v1",
        "field_identity_sha256": result.pop("identity_sha256"), **result}
