from __future__ import annotations

from typing import Any

from app.core.runtime_artifacts import RuntimeTimer, write_trace
from app.runtime_architecture.contracts import TraceEvent


def record_trace_event(
    event: TraceEvent | dict[str, Any],
    *,
    category: str = "runtime_architecture",
    operation: str | None = None,
    name_hint: str | None = None,
) -> str:
    trace_event = event if isinstance(event, TraceEvent) else TraceEvent.model_validate(event)
    return write_trace(
        category=category,
        operation=operation or trace_event.event_type,
        payload={
            "contract_version": "trace_event_record_v1",
            "event": trace_event.model_dump(),
        },
        name_hint=name_hint or trace_event.layer,
    )
