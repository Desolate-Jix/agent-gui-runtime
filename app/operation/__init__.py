from __future__ import annotations

from importlib import import_module
from typing import Any


_LAZY_EXPORTS = {
    "AVAILABLE_ACTIONS_CONTRACT": ("app.operation.path_graph", "AVAILABLE_ACTIONS_CONTRACT"),
    "EXECUTE_STEP_RESPONSE_CONTRACT": (
        "app.operation.step",
        "EXECUTE_STEP_RESPONSE_CONTRACT",
    ),
    "OperationSkill": ("app.operation.skills", "OperationSkill"),
    "OperationRuntimeContext": (
        "app.operation.runtime_context",
        "OperationRuntimeContext",
    ),
    "PATH_GRAPH_ACTION_CONTEXT_CONTRACT": (
        "app.operation.step",
        "PATH_GRAPH_ACTION_CONTEXT_CONTRACT",
    ),
    "VISUAL_ASSET_MATCH_CONTRACT": (
        "app.operation.visual_asset_matching",
        "VISUAL_ASSET_MATCH_CONTRACT",
    ),
    "build_available_actions": (
        "app.operation.path_graph",
        "build_available_actions",
    ),
    "build_execute_step_plan": (
        "app.operation.step",
        "build_execute_step_plan",
    ),
    "build_operation_skill_catalog": (
        "app.operation.skills",
        "build_operation_skill_catalog",
    ),
    "build_operation_runtime_context": (
        "app.operation.runtime_context",
        "build_operation_runtime_context",
    ),
    "build_path_graph_action_context": (
        "app.operation.step",
        "build_path_graph_action_context",
    ),
    "build_read_region_batch_report": (
        "app.operation.reading",
        "build_read_region_batch_report",
    ),
    "build_ui_diff_verification": (
        "app.operation.verification",
        "build_ui_diff_verification",
    ),
    "extract_ocr_text_lines": (
        "app.operation.reading",
        "extract_ocr_text_lines",
    ),
    "list_operation_skills": (
        "app.operation.skills",
        "list_operation_skills",
    ),
    "match_visual_asset": (
        "app.operation.visual_asset_matching",
        "match_visual_asset",
    ),
    "operation_trace_link": (
        "app.operation.runtime_context",
        "operation_trace_link",
    ),
    "run_region_click": (
        "app.operation.region_click",
        "run_region_click",
    ),
    "should_verify_mouse_tester_semantics": (
        "app.operation.mousetester",
        "should_verify_mouse_tester_semantics",
    ),
    "target_bbox_from_recommended": (
        "app.operation.mousetester",
        "target_bbox_from_recommended",
    ),
    "validate_operation_runtime_context": (
        "app.operation.runtime_context",
        "validate_operation_runtime_context",
    ),
    "verify_mouse_tester_post_click_semantics": (
        "app.operation.mousetester",
        "verify_mouse_tester_post_click_semantics",
    ),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
