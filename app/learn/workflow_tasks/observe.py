from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.core.runtime_artifacts import RuntimeTimer, write_trace
from app.learn.interface_map import build_learned_interface_map
from app.learn.observe_enrichment.deep_review import apply_deep_review
from app.learn.observe_enrichment.path_graph import (
    apply_learned_path_graph_to_screen_map,
    runtime_graph_from_screen_map_for_interface_map,
)
from app.learn.observe_enrichment.screen_map_builder import (
    build_observation_screen_map,
    suggested_state_hint_from_observation,
)
from app.learn.observe_enrichment.visual_assets import (
    safe_visual_asset_run_name,
    should_learn_visual_assets,
    skipped_visual_asset_learning,
)
from app.learn.visual_asset_crops import build_visual_assets_from_screen_map
from app.operation.observe.contracts import (
    ObserveScreenTaskFailure,
    ObserveScreenTaskInput,
    ObserveScreenTaskResult,
)
from app.operation.observe.degraded import (
    build_degraded_observation,
    image_size_payload,
)
from app.operation.observe.image_source import resolve_observe_image_source
from app.operation.observe.screen_reader import read_screen
from app.operation.observe.service import run_base_observation
from app.vision.factory import VisionProviderFactory
from app.vision.model_io import model_io_failure_payload

TraceWriter = Callable[..., str]


def run_observe_task(
    task: ObserveScreenTaskInput,
    *,
    project_root: Path,
    image_source_resolver: Callable[..., tuple[str, dict[str, Any] | None]] = (
        resolve_observe_image_source
    ),
    screen_reader: Callable[..., Any] = read_screen,
    degraded_builder: Callable[..., dict[str, Any]] = (
        build_degraded_observation
    ),
    image_size_builder: Callable[..., dict[str, int]] = image_size_payload,
    provider_factory: Any = VisionProviderFactory,
    visual_asset_builder: Callable[..., dict[str, Any]] = (
        build_visual_assets_from_screen_map
    ),
    interface_map_builder: Callable[..., dict[str, Any]] = (
        build_learned_interface_map
    ),
    trace_writer: TraceWriter = write_trace,
    artifacts_dir: Path | None = None,
    timer: RuntimeTimer | None = None,
) -> ObserveScreenTaskResult:
    active_timer = timer or RuntimeTimer()
    root = project_root.resolve()
    output_root = (artifacts_dir or root / "artifacts").resolve()
    try:
        base_result = run_base_observation(
            task,
            image_source_resolver=image_source_resolver,
            screen_reader=screen_reader,
            degraded_builder=degraded_builder,
            image_size_builder=image_size_builder,
            timer=active_timer,
        )
        if base_result.outcome != "completed":
            failure = base_result.failure
            raise RuntimeError(
                failure.details
                if failure is not None
                else "Base screen observation failed"
            )

        image_path = str(base_result.payload["image_path"])
        live_capture = base_result.payload.get("live_capture")
        result = dict(base_result.payload["observation"])
        result["contract_version"] = "screen_observation_v1"
        result.update(_mode_payload(task))
        result["live_capture"] = live_capture
        result["operation_context"] = base_result.payload["operation_context"]
        result["operation_trace_link"] = base_result.payload[
            "operation_trace_link"
        ]
        result["suggested_state_hint"] = (
            suggested_state_hint_from_observation(result)
        )
        result["screen_map"] = build_observation_screen_map(
            result,
            task=task,
            image_path=image_path,
        )
        result["screen_map"] = apply_learned_path_graph_to_screen_map(
            result["screen_map"],
            result=result,
            task=task,
            image_path=image_path,
        )
        if task.learn_depth == "deep":
            with active_timer.step("learn_deep_review"):
                deep_result = apply_deep_review(
                    result=result,
                    screen_map=result["screen_map"],
                    task=task,
                    provider_factory=provider_factory,
                )
            result["screen_map"] = deep_result["screen_map"]
            result["path_graph_deep_review"] = deep_result[
                "path_graph_deep_review"
            ]
            result["path_graph_delta"] = deep_result["path_graph_delta"]
            result["element_memory_init_plan"] = deep_result[
                "element_memory_init_plan"
            ]
        if should_learn_visual_assets(task):
            page_type = (
                result["screen_map"].get("page_type")
                or result.get("state_guess")
                or task.state_hint
            )
            if not Path(image_path).exists():
                visual_asset_learning = skipped_visual_asset_learning(
                    image_path=image_path,
                    reason="missing_source_image",
                    app_id=task.app_name or result.get("app_name"),
                    page_type=page_type,
                    learn_depth=task.learn_depth,
                )
            else:
                try:
                    with active_timer.step("learn_visual_assets"):
                        visual_asset_learning = visual_asset_builder(
                            result["screen_map"],
                            source_image_path=image_path,
                            output_dir=output_root
                            / "visual-assets"
                            / safe_visual_asset_run_name(
                                task.app_name
                                or result.get("app_name")
                                or Path(image_path).stem
                            ),
                            app_id=task.app_name or result.get("app_name"),
                            page_type=page_type,
                            capture_id=str(image_path),
                            learn_depth=task.learn_depth,
                        )
                except Exception as exc:
                    visual_asset_learning = skipped_visual_asset_learning(
                        image_path=image_path,
                        reason="visual_asset_learning_failed",
                        app_id=task.app_name or result.get("app_name"),
                        page_type=page_type,
                        learn_depth=task.learn_depth,
                        error_detail=str(exc),
                    )
            result["visual_asset_learning"] = visual_asset_learning
            result["screen_map"]["visual_assets"] = (
                visual_asset_learning.get("visual_assets")
            )
            with active_timer.step("build_learned_interface_map"):
                learned_interface_map = interface_map_builder(
                    runtime_graph_from_screen_map_for_interface_map(
                        result["screen_map"],
                        result=result,
                    ),
                    visual_asset_learning.get("visual_assets"),
                )
            result["learned_interface_map"] = learned_interface_map
            result["screen_map"]["learned_interface_map_summary"] = (
                learned_interface_map.get("summary")
            )
        result["agent_next_steps"] = [
            (
                "Read screen_map.candidates to decide what the user likely "
                "wants; it is a semantic map, not executable coordinates."
            ),
            (
                "Use screen_map.state_id and suggested_state_hint as the "
                "default context for POST /vision/locate_target unless the "
                "user overrides it."
            ),
            (
                "When a concrete target is chosen, call POST "
                "/vision/locate_target with that candidate label/goal."
            ),
            (
                "Execute only through POST /action/execute_recognition_plan "
                "after pre_click_decision allows it."
            ),
        ]
        result["timings"] = active_timer.to_dict()
        if task.write_policy.trace:
            result["trace_path"] = trace_writer(
                category="vision",
                operation=(
                    "learn_mode_fast_observe"
                    if task.agent_mode == "learn"
                    else "observe_screen"
                ),
                payload={
                    "success": True,
                    "request": task.model_dump(mode="json"),
                    "result": result,
                },
                name_hint=task.app_name or Path(image_path).stem,
            )
        else:
            result["trace_path"] = None
        return ObserveScreenTaskResult(
            outcome="completed",
            payload=result,
        )
    except Exception as exc:
        timings = active_timer.to_dict()
        model_io = model_io_failure_payload(exc)
        payload: dict[str, Any] = {"timings": timings}
        if model_io is not None:
            payload["model_io"] = model_io
        if task.write_policy.trace:
            try:
                payload["trace_path"] = trace_writer(
                    category="vision",
                    operation=(
                        "learn_mode_fast_observe"
                        if task.agent_mode == "learn"
                        else "observe_screen"
                    ),
                    payload={
                        "success": False,
                        "request": task.model_dump(mode="json"),
                        "error": str(exc),
                        "timings": timings,
                        **({"model_io": model_io} if model_io else {}),
                    },
                    name_hint=task.app_name or "observe_screen",
                )
            except Exception:
                payload["trace_path"] = None
        return ObserveScreenTaskResult(
            outcome="failed",
            payload=payload,
            failure=ObserveScreenTaskFailure(
                code="observe_screen_failed",
                details=str(exc),
            ),
        )


def _mode_payload(task: ObserveScreenTaskInput) -> dict[str, Any]:
    if task.agent_mode == "learn":
        contract_version = (
            "learn_screen_deep_v1"
            if task.learn_depth == "deep"
            else "learn_screen_fast_v1"
        )
    else:
        contract_version = "execute_plan_v1"
    return {
        "agent_mode": task.agent_mode,
        "learn_depth": task.learn_depth,
        "mode_contract_version": contract_version,
        "write_policy": task.write_policy.model_dump(mode="json"),
    }
