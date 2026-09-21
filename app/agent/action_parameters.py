"""组合审核动作参数引用与当前定位几何校验。"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.agent.scroll_parameters import scroll_parameter_fields, validate_scroll_grounding_geometry
from app.agent.text_parameters import (
    text_parameter_fields, validate_text_dispatch_geometry, validate_text_parameter_reference,
)

def reviewed_action_parameter_fields(subject: Mapping[str, Any], *, semantic_action: str | None = None) -> dict[str, Any]:
    """滚动保留旧声明；填写只投影不含原文的审核引用。"""
    fields = scroll_parameter_fields(subject, semantic_action=semantic_action)
    fields.update(text_parameter_fields(subject, semantic_action=semantic_action))
    return fields

def validate_reviewed_action_grounding_geometry(subject: Mapping[str, Any], grounding: Mapping[str, Any]) -> None:
    """复用半开边界与整数像素规则；字段和锚点绑定由审核资产校验。"""
    fields = reviewed_action_parameter_fields(subject)
    if "scroll_parameters" in fields:
        validate_scroll_grounding_geometry(subject, grounding)
    if "text_parameters_ref" not in fields:
        return
    validate_text_parameter_reference(fields["text_parameters_ref"])
    try:
        bbox, point, viewport = grounding["bbox"], grounding["click_point"], grounding["viewport_size"]
        validate_text_dispatch_geometry(
            tuple(bbox[key] for key in ("x", "y", "w", "h")),
            (viewport["width"], viewport["height"]),
            (point["x"], point["y"]),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("text grounding geometry is invalid") from exc
