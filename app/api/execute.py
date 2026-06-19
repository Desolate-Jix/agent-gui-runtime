from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from app.api.action import execute_recognition_plan as dispatch_recognition_plan
from app.api.action import scroll as dispatch_scroll
from app.api.action import type_text as dispatch_type_text
from app.core.runtime_artifacts import RuntimeTimer, write_trace
from app.execute.available_actions import build_available_actions
from app.execute.path_graph_step import build_execute_step_plan
from app.learn.path_graph_resolver import resolve_runtime_path_graph
from app.models.request import (
    AvailableActionsRequest,
    ExecuteRecognitionPlanRequest,
    ExecuteStepRequest,
    ScrollRequest,
    TypeTextRequest,
)
from app.models.response import APIResponse, ErrorModel


router = APIRouter(prefix="/execute", tags=["execute"])


@router.post("/available_actions", response_model=APIResponse)
def available_actions(request: AvailableActionsRequest) -> APIResponse:
    timer = RuntimeTimer()
    try:
        with timer.step("load_runtime_path_graph"):
            graph = _load_runtime_path_graph(request.runtime_path_graph, request.runtime_graph_path)
        with timer.step("resolve_runtime_path_graph"):
            resolution = resolve_runtime_path_graph(
                graph,
                screen_inventory=request.screen_inventory,
                scroll_containers=request.scroll_containers,
                requested_state_id=request.current_state_id,
                safety=request.safety,
            )
        with timer.step("build_available_actions", state_id=resolution.get("state_id")):
            actions = build_available_actions(
                graph,
                current_state_id=resolution.get("state_id"),
                include_guarded_apply=bool(request.safety.get("allow_apply_entry")),
                path_graph_resolution=resolution,
            )
        result = {
            "contract_version": "available_actions_response_v1",
            "capture_live_requested": request.capture_live,
            "capture_live_used": False,
            "path_graph_resolution": resolution,
            "available_actions": actions,
            "task_context": request.task_context,
        }
        result["timings"] = timer.to_dict()
        trace_path = write_trace(
            category="execute",
            operation="available_actions",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=graph.get("app_id") or "path_graph",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Available actions generated", data=result, error=None)
    except Exception as exc:
        timings = timer.to_dict()
        trace_path = write_trace(
            category="execute",
            operation="available_actions",
            payload={"success": False, "request": request.model_dump(), "error": str(exc), "timings": timings},
            name_hint="path_graph",
        )
        return APIResponse(
            success=False,
            message="Available actions failed",
            data={"trace_path": trace_path, "timings": timings},
            error=ErrorModel(code="available_actions_failed", details=str(exc)),
        )


@router.post("/step", response_model=APIResponse)
def execute_step(request: ExecuteStepRequest) -> APIResponse:
    timer = RuntimeTimer()
    try:
        with timer.step("load_runtime_path_graph"):
            graph = _load_runtime_path_graph(request.runtime_path_graph, request.runtime_graph_path)
        state_id = _state_id_from_request(request)
        with timer.step("resolve_selected_action", requested_action_id=request.requested_action_id, state_id=state_id):
            selected_action = _selected_action_from_request(graph, request, state_id=state_id)
        with timer.step("build_execute_step_plan", action_template_id=selected_action.get("action_template_id")):
            result = build_execute_step_plan(
                graph,
                selected_action,
                state_id=state_id,
                safety=request.safety,
                dry_run=request.dry_run,
            )
        result["available_actions_trace_path"] = request.available_actions_trace_path
        result["dispatch_low_level_requested"] = request.dispatch_low_level
        result["dispatch_low_level_executed"] = False
        if request.dispatch_low_level and result.get("status") != "rejected":
            with timer.step("dispatch_low_level", low_level_action_type=result.get("low_level_action_type")):
                dispatch_result = _dispatch_low_level_step(result)
            result.update(dispatch_result)
        _update_path_graph_runtime_state_verification(result)
        result["timings"] = timer.to_dict()
        trace_path = write_trace(
            category="execute",
            operation="execute_step",
            payload={"success": result.get("status") != "rejected", "request": request.model_dump(), "result": result},
            name_hint=result.get("action_template_id") or "path_graph_step",
        )
        result["execute_step_trace_path"] = trace_path
        return APIResponse(
            success=result.get("status") != "rejected",
            message="Execute step planned" if result.get("status") != "rejected" else "Execute step rejected",
            data=result,
            error=None
            if result.get("status") != "rejected"
            else ErrorModel(code="execute_step_rejected", details=result),
        )
    except Exception as exc:
        timings = timer.to_dict()
        trace_path = write_trace(
            category="execute",
            operation="execute_step",
            payload={"success": False, "request": request.model_dump(), "error": str(exc), "timings": timings},
            name_hint="path_graph_step",
        )
        return APIResponse(
            success=False,
            message="Execute step failed",
            data={"trace_path": trace_path, "timings": timings},
            error=ErrorModel(code="execute_step_failed", details=str(exc)),
        )


def _state_id_from_request(request: ExecuteStepRequest) -> str | None:
    if request.current_state_id:
        return request.current_state_id
    if isinstance(request.path_graph_resolution, dict):
        value = request.path_graph_resolution.get("state_id")
        return str(value) if value else None
    return None


def _update_path_graph_runtime_state_verification(result: dict[str, Any]) -> None:
    runtime_state = result.get("path_graph_runtime_state_v1")
    if not isinstance(runtime_state, dict):
        return
    verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
    if verification.get("low_level_success") is True:
        runtime_state["verification_status"] = "verified"
    elif verification.get("low_level_success") is False:
        runtime_state["verification_status"] = str(verification.get("status") or "failed")
    elif result.get("status") == "rejected":
        runtime_state["verification_status"] = "rejected"
    else:
        runtime_state["verification_status"] = "planned"


def _selected_action_from_request(
    graph: dict[str, Any],
    request: ExecuteStepRequest,
    *,
    state_id: str | None,
) -> dict[str, Any]:
    action = dict(request.selected_action) if isinstance(request.selected_action, dict) else {}
    requested_action_id = str(
        request.requested_action_id
        or action.get("action_template_id")
        or action.get("action_id")
        or ""
    ).strip()
    if not action and requested_action_id:
        available = build_available_actions(
            graph,
            current_state_id=state_id,
            include_guarded_apply=bool(request.safety.get("allow_apply_entry")),
            path_graph_resolution={"state_id": state_id} if state_id else None,
        )
        actions = available.get("actions") if isinstance(available, dict) else []
        for item in actions if isinstance(actions, list) else []:
            if not isinstance(item, dict):
                continue
            if str(item.get("action_template_id") or item.get("action_id") or "") == requested_action_id:
                action = dict(item)
                break
        if not action:
            action = {"action_template_id": requested_action_id, "action_id": requested_action_id}
    if requested_action_id:
        action.setdefault("action_template_id", requested_action_id)
        action.setdefault("action_id", requested_action_id)
    if request.input_text is not None:
        action["input_text"] = request.input_text
    if isinstance(request.target_point, dict):
        action["target_point"] = dict(request.target_point)
    if request.approved_plan_id:
        action["approved_plan_id"] = request.approved_plan_id
    if request.clear_existing is not None:
        action["clear_existing"] = request.clear_existing
    if request.submit is not None:
        action["submit"] = request.submit
    return action


def _dispatch_low_level_step(step_result: dict[str, Any]) -> dict[str, Any]:
    action_type = step_result.get("low_level_action_type")
    request_payload = step_result.get("low_level_request")
    if not isinstance(request_payload, dict):
        return {
            "dispatch_low_level_executed": False,
            "dispatch_low_level_blocked_reason": "missing_low_level_request",
        }

    if action_type == "scroll":
        response = dispatch_scroll(ScrollRequest(**request_payload))
    elif action_type == "click":
        response = dispatch_recognition_plan(ExecuteRecognitionPlanRequest(**request_payload))
    elif action_type == "input":
        gate = _live_input_dispatch_gate(request_payload)
        if not gate.get("allowed"):
            return {
                "dispatch_low_level_executed": False,
                "dispatch_low_level_blocked_reason": gate.get("reason"),
                "live_input_gate": gate,
                "status": "blocked_by_input_gate",
                "verification": {
                    "verified": False,
                    "status": "blocked_by_input_gate",
                    "low_level_success": False,
                },
            }
        response = dispatch_type_text(TypeTextRequest(**request_payload))
    else:
        return {
            "dispatch_low_level_executed": False,
            "dispatch_low_level_blocked_reason": f"unsupported_low_level_action_type:{action_type}",
        }

    response_payload = response.model_dump()
    low_level_trace_path = _extract_low_level_trace_path(response_payload)
    return {
        "dispatch_low_level_executed": True,
        "low_level_response": response_payload,
        "low_level_trace_path": low_level_trace_path,
        "status": "dispatched" if response.success else "low_level_failed",
        "verification": {
            "verified": None,
            "status": "low_level_response_recorded" if response.success else "low_level_failed",
            "low_level_success": response.success,
        },
    }


def _live_input_dispatch_gate(request_payload: dict[str, Any]) -> dict[str, Any]:
    if bool(request_payload.get("dry_run", True)):
        return {
            "contract_version": "live_input_dispatch_gate_v1",
            "allowed": True,
            "reason": "dry_run_input_allowed",
        }
    metadata = request_payload.get("metadata") if isinstance(request_payload.get("metadata"), dict) else {}
    safety = metadata.get("safety") if isinstance(metadata.get("safety"), dict) else {}
    input_policy = metadata.get("input_policy") if isinstance(metadata.get("input_policy"), dict) else {}
    category = str(metadata.get("input_category") or input_policy.get("input_category") or "").strip()
    allowed_categories = safety.get("allowed_input_categories")
    if not isinstance(allowed_categories, list):
        allowed_categories = ["public_search_query"] if safety.get("allow_live_input") is True else []
    allowed_category_keys = {str(item).strip() for item in allowed_categories if str(item).strip()}
    if safety.get("allow_live_input") is not True:
        return {
            "contract_version": "live_input_dispatch_gate_v1",
            "allowed": False,
            "reason": "live_input_not_enabled",
            "input_category": category,
            "allowed_input_categories": sorted(allowed_category_keys),
        }
    if not category or category not in allowed_category_keys:
        return {
            "contract_version": "live_input_dispatch_gate_v1",
            "allowed": False,
            "reason": "input_category_not_allowed",
            "input_category": category,
            "allowed_input_categories": sorted(allowed_category_keys),
        }
    if bool(request_payload.get("submit")):
        if category == "public_search_query" and input_policy.get("submit_allowed") is True:
            return {
                "contract_version": "live_input_dispatch_gate_v1",
                "allowed": True,
                "reason": "allowed_public_search_submit",
                "input_category": category,
                "allowed_input_categories": sorted(allowed_category_keys),
            }
        return {
            "contract_version": "live_input_dispatch_gate_v1",
            "allowed": False,
            "reason": "submit_not_allowed_for_live_input_gate",
            "input_category": category,
            "allowed_input_categories": sorted(allowed_category_keys),
        }
    return {
        "contract_version": "live_input_dispatch_gate_v1",
        "allowed": True,
        "reason": "allowed_public_live_input",
        "input_category": category,
        "allowed_input_categories": sorted(allowed_category_keys),
    }


def _extract_low_level_trace_path(response_payload: dict[str, Any]) -> str | None:
    data = response_payload.get("data") if isinstance(response_payload, dict) else None
    if not isinstance(data, dict):
        return None
    result = data.get("result") if isinstance(data.get("result"), dict) else data
    if isinstance(result, dict) and isinstance(result.get("trace_path"), str):
        return result["trace_path"]
    return None


def _load_runtime_path_graph(inline_graph: dict[str, Any], graph_path: str | None) -> dict[str, Any]:
    if inline_graph:
        return inline_graph
    if not graph_path:
        raise ValueError("runtime_graph_path or runtime_path_graph is required")
    path = Path(graph_path)
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{graph_path} must contain a JSON object")
    return payload
