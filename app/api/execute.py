from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from app.api.action import execute_recognition_plan as dispatch_recognition_plan
from app.api.action import scroll as dispatch_scroll
from app.api.action import type_text as dispatch_type_text
from app.core.runtime_artifacts import RuntimeTimer, write_trace
from app.operation.path_graph import build_available_actions
from app.operation.reading import build_read_region_batch_report
from app.operation.step import build_execute_step_plan
from app.operation.verification import build_ui_diff_verification
from app.learn.path_graph_resolver import resolve_runtime_path_graph
from app.api.models.request import (
    AvailableActionsRequest,
    ExecuteFormInventoryRequest,
    ExecuteObserveRequest,
    ExecuteReadRegionBatchRequest,
    ExecuteRecognitionPlanRequest,
    ExecuteStepRequest,
    ExecuteVerifyDiffRequest,
    ScrollRequest,
    TypeTextRequest,
)
from app.api.models.response import APIResponse, ErrorModel
from app.seek.execute_observation import build_seek_execute_observation
from app.seek.form_inventory import build_seek_form_field_inventory


router = APIRouter(prefix="/execute", tags=["execute"])


@router.post("/observe", response_model=APIResponse)
def execute_observe(request: ExecuteObserveRequest) -> APIResponse:
    timer = RuntimeTimer()
    try:
        with timer.step("build_execute_observation", app_id=request.app_id):
            if str(request.app_id or "").casefold() in {"seek", "nz.seek.com", "seek.co.nz"}:
                result = build_seek_execute_observation(
                    request.observation,
                    application_flow_state=request.application_flow_state,
                )
            else:
                result = _generic_execute_observation(request)
        result["timings"] = timer.to_dict()
        trace_path = write_trace(
            category="execute",
            operation="execute_observe",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=request.app_id or result.get("page_state") or "execute_observe",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Execute observation built", data=result, error=None)
    except Exception as exc:
        timings = timer.to_dict()
        trace_path = write_trace(
            category="execute",
            operation="execute_observe",
            payload={"success": False, "request": request.model_dump(), "error": str(exc), "timings": timings},
            name_hint=request.app_id or "execute_observe",
        )
        return APIResponse(
            success=False,
            message="Execute observation failed",
            data={"trace_path": trace_path, "timings": timings},
            error=ErrorModel(code="execute_observe_failed", details=str(exc)),
        )


@router.post("/verify_diff", response_model=APIResponse)
def verify_diff(request: ExecuteVerifyDiffRequest) -> APIResponse:
    timer = RuntimeTimer()
    try:
        with timer.step("build_ui_diff_verification", expected_change=request.expected_change):
            result = build_ui_diff_verification(
                request.before_image,
                request.after_image,
                expected_change=request.expected_change,
                target_bbox=request.target_bbox.model_dump() if request.target_bbox else None,
            )
        result["timings"] = timer.to_dict()
        trace_path = write_trace(
            category="execute",
            operation="verify_diff",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=request.expected_change or "verify_diff",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Diff verification completed", data=result, error=None)
    except Exception as exc:
        timings = timer.to_dict()
        trace_path = write_trace(
            category="execute",
            operation="verify_diff",
            payload={"success": False, "request": request.model_dump(), "error": str(exc), "timings": timings},
            name_hint=request.expected_change or "verify_diff",
        )
        return APIResponse(
            success=False,
            message="Diff verification failed",
            data={"trace_path": trace_path, "timings": timings},
            error=ErrorModel(code="verify_diff_failed", details=str(exc)),
        )


@router.post("/read_region_batch", response_model=APIResponse)
def read_region_batch(request: ExecuteReadRegionBatchRequest) -> APIResponse:
    timer = RuntimeTimer()
    try:
        with timer.step("build_read_region_batch_report", target_container_id=request.target_container_id):
            result = build_read_region_batch_report(
                target_container_id=request.target_container_id,
                target_bbox=request.target_bbox,
                captures=request.captures,
                max_captures=request.max_captures,
                stop_after_no_new_content=request.stop_after_no_new_content,
                wrong_scope_detected=request.wrong_scope_detected,
            )
        result["timings"] = timer.to_dict()
        trace_path = write_trace(
            category="execute",
            operation="read_region_batch",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=request.target_container_id,
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Region batch read merged", data=result, error=None)
    except Exception as exc:
        timings = timer.to_dict()
        trace_path = write_trace(
            category="execute",
            operation="read_region_batch",
            payload={"success": False, "request": request.model_dump(), "error": str(exc), "timings": timings},
            name_hint=request.target_container_id,
        )
        return APIResponse(
            success=False,
            message="Region batch read failed",
            data={"trace_path": trace_path, "timings": timings},
            error=ErrorModel(code="read_region_batch_failed", details=str(exc)),
        )


@router.post("/form_inventory", response_model=APIResponse)
def form_inventory(request: ExecuteFormInventoryRequest) -> APIResponse:
    timer = RuntimeTimer()
    try:
        with timer.step("build_form_field_inventory", app_id=request.app_id):
            if str(request.app_id or "").casefold() in {"seek", "nz.seek.com", "seek.co.nz"}:
                result = build_seek_form_field_inventory(
                    request.application_flow_state,
                    employer_question_inventory=request.employer_question_inventory,
                    application_answer_plan=request.application_answer_plan,
                )
            else:
                result = _generic_form_field_inventory(request)
        result["timings"] = timer.to_dict()
        trace_path = write_trace(
            category="execute",
            operation="form_inventory",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=request.app_id or result.get("form_state") or "form_inventory",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Form inventory built", data=result, error=None)
    except Exception as exc:
        timings = timer.to_dict()
        trace_path = write_trace(
            category="execute",
            operation="form_inventory",
            payload={"success": False, "request": request.model_dump(), "error": str(exc), "timings": timings},
            name_hint=request.app_id or "form_inventory",
        )
        return APIResponse(
            success=False,
            message="Form inventory failed",
            data={"trace_path": trace_path, "timings": timings},
            error=ErrorModel(code="form_inventory_failed", details=str(exc)),
        )


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


def _generic_execute_observation(request: ExecuteObserveRequest) -> dict[str, Any]:
    items = _generic_observation_items(request.observation, request.application_flow_state)
    actions = [item for item in items if str(item.get("role") or "").casefold() in {"button", "link", "input", "textbox", "radio", "checkbox"}]
    danger_actions = [
        item
        for item in actions
        if any(term in str(item.get("text") or "").casefold() for term in ("submit", "send", "complete", "delete", "purchase", "pay"))
    ]
    return {
        "contract_version": "execute_observation_v1",
        "page_state": "unknown",
        "state_confidence": 0.2 if items else 0.0,
        "current_step": request.application_flow_state.get("current_step"),
        "source_state_type": request.application_flow_state.get("state_type"),
        "evidence": [{"text": str(item.get("text") or "")[:240]} for item in items[:20] if item.get("text")],
        "regions": [],
        "primary_actions": actions[:40],
        "danger_actions": danger_actions[:20],
        "profile_mutation_actions": [],
        "available_actions": actions[:80],
        "form_fields_hint": [item for item in actions if str(item.get("role") or "").casefold() in {"input", "textbox", "radio", "checkbox"}][:80],
        "safety_blockers": [
            {
                "kind": "danger_action_visible",
                "reason": "Generic execute observation found submit/send/delete/purchase/pay-like action text.",
                "actions": danger_actions[:20],
            }
        ]
        if danger_actions
        else [],
        "trace_path": request.observation.get("trace_path"),
    }


def _generic_form_field_inventory(request: ExecuteFormInventoryRequest) -> dict[str, Any]:
    flow = request.application_flow_state if isinstance(request.application_flow_state, dict) else {}
    inventory = flow.get("application_form_inventory") if isinstance(flow.get("application_form_inventory"), dict) else {}
    fields: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for item in inventory.get("fields") or []:
        if isinstance(item, dict):
            fields.append(_generic_form_field(item))
    for item in inventory.get("actions") or []:
        if isinstance(item, dict):
            actions.append(_compact_observation_item(item))
    return {
        "contract_version": "form_field_inventory_v1",
        "form_state": flow.get("current_step") or flow.get("state_type") or "unknown",
        "fields": fields,
        "continue_action": _first_generic_action(actions, ("continue", "next", "review", "save")),
        "danger_actions": [
            action
            for action in actions
            if any(term in str(action.get("text") or "").casefold() for term in ("submit", "send", "complete", "delete", "pay", "purchase"))
        ],
        "profile_mutation_actions": [
            action
            for action in actions
            if any(term in str(action.get("text") or "").casefold() for term in ("add ", "edit", "upload", "replace", "update profile"))
        ],
        "source_contracts": {
            "application_flow_state": flow.get("contract_version"),
            "employer_question_inventory": request.employer_question_inventory.get("contract_version"),
            "application_answer_plan": request.application_answer_plan.get("contract_version"),
        },
    }


def _generic_form_field(item: dict[str, Any]) -> dict[str, Any]:
    text = str(item.get("text") or item.get("label") or "").strip()
    role = str(item.get("role") or "unknown")
    return {
        "field_id": item.get("id") or text,
        "label": text,
        "field_type": role,
        "field_bbox": item.get("bbox"),
        "required": bool(item.get("required", False)),
        "answer_source_required": True,
        "source": item.get("collection") or item.get("source") or "application_form_inventory",
    }


def _first_generic_action(actions: list[dict[str, Any]], terms: tuple[str, ...]) -> dict[str, Any] | None:
    for action in actions:
        text = str(action.get("text") or "").casefold()
        if any(term in text for term in terms):
            return action
    return None


def _generic_observation_items(observation: dict[str, Any], flow_state: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    inventory = flow_state.get("application_form_inventory") if isinstance(flow_state.get("application_form_inventory"), dict) else {}
    for key in ("fields", "actions"):
        values = inventory.get(key)
        if isinstance(values, list):
            items.extend(_compact_observation_item(item) for item in values if isinstance(item, dict))
    evidence = flow_state.get("evidence") if isinstance(flow_state.get("evidence"), dict) else {}
    for text in evidence.get("texts") or []:
        if str(text or "").strip():
            items.append({"text": str(text), "role": "text", "bbox": None, "source": "flow_state_evidence"})
    screen_reading = observation.get("screen_reading") if isinstance(observation.get("screen_reading"), dict) else {}
    for key in ("ui_elements", "elements", "actions"):
        values = screen_reading.get(key)
        if isinstance(values, list):
            items.extend(_compact_observation_item(item) for item in values if isinstance(item, dict))
    return items


def _compact_observation_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "text": str(item.get("text") or item.get("label") or "")[:240],
        "role": item.get("role"),
        "bbox": item.get("bbox"),
        "source": item.get("collection") or item.get("source"),
    }


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
