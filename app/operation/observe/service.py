from __future__ import annotations

from typing import Any, Callable

from app.core.runtime_artifacts import RuntimeTimer
from app.operation.observe.contracts import (
    ObserveScreenReadRequest,
    ObserveScreenReadResult,
    ObserveScreenTaskFailure,
    ObserveScreenTaskInput,
    ObserveScreenTaskResult,
)
from app.operation.runtime_context import (
    build_operation_runtime_context,
    operation_trace_link,
)


def _provider_mode(provider_mode: str | None) -> str:
    requested = str(provider_mode or "").strip().casefold()
    if requested in {"", "local", "local_grounding"}:
        return "local_understanding"
    return str(provider_mode).strip()


def run_base_observation(
    task: ObserveScreenTaskInput,
    *,
    image_source_resolver: Callable[
        [ObserveScreenTaskInput],
        tuple[str, dict[str, Any] | None],
    ],
    screen_reader: Callable[
        [ObserveScreenReadRequest],
        ObserveScreenReadResult,
    ],
    degraded_builder: Callable[..., dict[str, Any]],
    image_size_builder: Callable[..., dict[str, int]],
    timer: RuntimeTimer | None = None,
) -> ObserveScreenTaskResult:
    active_timer = timer or RuntimeTimer()
    try:
        with active_timer.step("resolve_image_source", capture_live=task.capture_live):
            image_path, live_capture = image_source_resolver(task)
        viewport_size = image_size_builder(
            image_path=image_path,
            live_capture=live_capture,
        )
        operation_context = build_operation_runtime_context(
            request=task,
            skill_id="observe_screen",
            semantic_action="observe_screen",
            side_effect_class="read_only",
            requires_gate=False,
            capture_id=image_path,
            viewport_size=viewport_size,
            evidence_refs=[image_path],
        )
        metadata = dict(task.metadata)
        current_anchors = metadata.get("ocr_anchors")
        if isinstance(current_anchors, dict):
            metadata["ocr_anchors"] = {
                "enabled": True,
                "max_anchors": "all",
                **current_anchors,
            }
        else:
            metadata["ocr_anchors"] = current_anchors or {
                "enabled": True,
                "max_anchors": "all",
            }
        read_request = ObserveScreenReadRequest(
            image_path=image_path,
            task=task.task,
            app_name=task.app_name,
            state_hint=task.state_hint,
            provider_mode=_provider_mode(task.provider_mode),
            agent_mode=task.agent_mode,
            learn_depth=task.learn_depth,
            write_policy=task.write_policy,
            metadata=metadata,
            operation_context=operation_context,
        )
        with active_timer.step("screen_reading"):
            screen_result = screen_reader(read_request)
        if screen_result.success and isinstance(screen_result.payload, dict):
            observation = dict(screen_result.payload)
        else:
            with active_timer.step("observe_degraded_fallback"):
                observation = degraded_builder(
                    task=task,
                    image_path=image_path,
                    live_capture=live_capture,
                    screen_result=screen_result,
                )
        return ObserveScreenTaskResult(
            outcome="completed",
            payload={
                "image_path": image_path,
                "live_capture": live_capture,
                "observation": observation,
                "operation_context": operation_context,
                "operation_trace_link": operation_trace_link(
                    operation_context,
                    result_status="success",
                    evidence_refs=[image_path],
                ),
                "timings": active_timer.to_dict(),
            },
        )
    except Exception as exc:
        return ObserveScreenTaskResult(
            outcome="failed",
            payload={"timings": active_timer.to_dict()},
            failure=ObserveScreenTaskFailure(
                code="observe_screen_failed",
                details=str(exc),
            ),
        )
