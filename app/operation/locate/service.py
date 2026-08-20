from __future__ import annotations

from typing import Any, Callable

from app.core.runtime_artifacts import RuntimeTimer
from app.operation.locate.contracts import (
    LocateRecognitionPlanRequest,
    LocateRecognitionPlanResult,
    LocateSingleTargetTaskInput,
    LocateSingleTargetTaskResult,
    LocateTaskFailure,
)
from app.operation.runtime_context import operation_trace_link

RecognitionPlanRunner = Callable[
    [LocateRecognitionPlanRequest],
    LocateRecognitionPlanResult,
]
PathMapReviewBuilder = Callable[..., dict[str, Any]]


def run_single_target_locate(
    task: LocateSingleTargetTaskInput,
    *,
    recognition_plan_runner: RecognitionPlanRunner,
    path_map_review_builder: PathMapReviewBuilder,
    timer: RuntimeTimer | None = None,
) -> LocateSingleTargetTaskResult:
    active_timer = timer or RuntimeTimer()
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
    request = LocateRecognitionPlanRequest(
        image_path=task.image_path,
        task=task.task,
        app_name=task.app_name,
        goal=task.goal,
        state_hint=task.state_hint,
        provider_mode=task.provider_mode,
        agent_mode=task.agent_mode,
        learn_depth=task.learn_depth,
        write_policy=task.write_policy,
        metadata=metadata,
        top_k=task.top_k,
        observe_trace_path=task.observe_trace_path,
        operation_context=task.operation_context,
    )
    with active_timer.step("recognition_plan"):
        response = recognition_plan_runner(request)
    if not response.success or not isinstance(response.payload, dict):
        error = response.error
        if isinstance(error, dict):
            code = str(error.get("code") or "recognition_plan_failed")
            details = str(error.get("details") or response.message)
        else:
            code = "recognition_plan_failed"
            details = str(error or response.message)
        return LocateSingleTargetTaskResult(
            outcome="failed",
            payload={
                "upstream_message": response.message,
                "upstream_data": response.payload,
                "upstream_error": response.error,
                "timings": active_timer.to_dict(),
            },
            failure=LocateTaskFailure(code=code, details=details),
        )

    recognition_result = dict(response.payload)
    recommended_target = _locatable_target_from_plan_result(
        recognition_result
    )
    selected_click_point = (
        recognition_result.get("pre_click_decision") or {}
    ).get("selected_click_point")
    located_bbox = _locatable_bbox(recommended_target)
    located_point = (
        selected_click_point
        if isinstance(selected_click_point, dict)
        else _locatable_point(recommended_target, located_bbox)
    )
    located_source = str(
        recommended_target.get("location_source")
        or "recommended_target.element.click_point"
    )
    path_map_review = path_map_review_builder(
        observe_reuse=task.observe_reuse,
        recognition_result=recognition_result,
        goal=task.goal,
        located_bbox=located_bbox,
        located_point=located_point,
    )
    observe_reuse_summary = {
        key: value
        for key, value in task.observe_reuse.items()
        if key not in {"ocr_anchors", "screen_map", "observe_result"}
    }
    execution_path = {
        **dict(recognition_result.get("execution_path") or {}),
        "action_executed": False,
        "coordinate_source": (
            "pre_click_decision_v1.selected_click_point"
        ),
        "located_coordinate_source": located_source,
        "ocr_anchor_reused_from_observe": (
            task.observe_reuse.get("status") == "ready"
        ),
        "ocr_anchor_reuse_source": task.observe_reuse.get("anchor_source"),
        "ocr_anchor_reuse_trace_path": (
            task.observe_reuse.get("trace_path")
            if task.observe_reuse.get("status") == "ready"
            else None
        ),
        "agent_must_call_for_click": (
            "POST /action/execute_recognition_plan"
        ),
    }
    payload = {
        "contract_version": "target_location_v1",
        **_mode_payload(task),
        "goal": task.goal,
        "image_path": task.image_path,
        "live_capture": task.live_capture,
        "recognition_plan": recognition_result,
        "pre_click_decision": recognition_result.get("pre_click_decision"),
        "selected_click_point": selected_click_point,
        "recommended_target": recommended_target,
        "located_bbox": located_bbox,
        "located_point": located_point,
        "location_status": (
            "pre_click_verified"
            if selected_click_point
            else (
                "requires_pre_click_confirmation"
                if located_point
                else "not_located"
            )
        ),
        "path_map_review": path_map_review,
        "operation_context": task.operation_context,
        "operation_trace_link": operation_trace_link(
            task.operation_context,
            result_status="success",
            evidence_refs=[task.image_path],
        ),
        "observe_trace_reuse": observe_reuse_summary,
        "execution_path": execution_path,
        "timings": active_timer.to_dict(),
    }
    return LocateSingleTargetTaskResult(
        outcome="completed",
        payload=payload,
    )


def _locatable_target_from_plan_result(
    result: dict[str, Any],
) -> dict[str, Any]:
    recommended = (
        result.get("recommended_target")
        if isinstance(result.get("recommended_target"), dict)
        else {}
    )
    if isinstance(recommended.get("element"), dict):
        recommended = dict(recommended)
        recommended.setdefault(
            "location_source",
            "recommended_target.element.click_point",
        )
        return recommended

    candidate_result = (
        result.get("candidate_result")
        if isinstance(result.get("candidate_result"), dict)
        else {}
    )
    sources = (
        ("candidates", "candidate_result.candidates[0]"),
        ("rejected", "candidate_result.rejected[0]"),
    )
    for source_key, source_name in sources:
        candidates = candidate_result.get(source_key)
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if not isinstance(candidate.get("element"), dict):
                continue
            selected = dict(candidate)
            selected["location_source"] = source_name
            return selected
    return {}


def _locatable_bbox(
    target: dict[str, Any],
) -> dict[str, Any] | None:
    refined = target.get("refined_bbox")
    if isinstance(refined, dict):
        return refined
    element = (
        target.get("element")
        if isinstance(target.get("element"), dict)
        else {}
    )
    bbox = element.get("bbox")
    return bbox if isinstance(bbox, dict) else None


def _locatable_point(
    target: dict[str, Any],
    bbox: dict[str, Any] | None,
) -> dict[str, int] | None:
    element = (
        target.get("element")
        if isinstance(target.get("element"), dict)
        else {}
    )
    point = element.get("click_point")
    if isinstance(point, dict):
        return {
            "x": int(point.get("x", 0)),
            "y": int(point.get("y", 0)),
        }
    if not isinstance(bbox, dict):
        return None
    width = int(bbox.get("w", bbox.get("width", 0)) or 0)
    height = int(bbox.get("h", bbox.get("height", 0)) or 0)
    if width <= 0 or height <= 0:
        return None
    return {
        "x": int(bbox.get("x", 0)) + width // 2,
        "y": int(bbox.get("y", 0)) + height // 2,
    }


def _mode_payload(task: LocateSingleTargetTaskInput) -> dict[str, Any]:
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

