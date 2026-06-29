from __future__ import annotations

from typing import Any, Callable

from app.core.runtime_artifacts import write_trace


def execute_trace_enabled(request: Any) -> bool:
    write_policy = request.write_policy.model_dump() if hasattr(request.write_policy, "model_dump") else {}
    return write_policy.get("trace", True) is not False


def execute_trace_operation(request: Any, operation: str | None) -> str | None:
    if operation != "execute_recognition_plan":
        return operation
    return "execute_mode_plan_preview" if bool(getattr(request, "dry_run", False)) else "execute_mode_click"


def write_execute_trace_if_enabled(
    request: Any,
    *,
    write_trace_fn: Callable[..., str] = write_trace,
    **kwargs: Any,
) -> str | None:
    if not execute_trace_enabled(request):
        return None
    payload = dict(kwargs)
    payload["operation"] = execute_trace_operation(request, payload.get("operation"))
    return write_trace_fn(**payload)
