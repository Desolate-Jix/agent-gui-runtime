"""Hybrid v1.2 的无动作选择、精修和审核投影任务。"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from collections.abc import Mapping
from typing import Any

from app.learn.hybrid.refinement_policy import decide_refinement
from app.learn.hybrid.selection_refinement import resolve_selection_refinement, validate_vista_actual_execution
from app.learn.hybrid.selection_review import project_selection_review
from app.learn.hybrid.target_selection import parse_gui_actor_selection


def run_hybrid_selection_task(payload: dict[str, Any], *, actual_execution: dict[str, Any] | None = None, refinement_execution: dict[str, Any] | None = None, cancellation_event: Any | None = None) -> dict[str, Any]:
    """只处理已存在的原始输出；provider 未 ready 时明确停止。"""
    if not isinstance(payload, dict) or "project_root" in payload:
        raise ValueError("Hybrid selection task payload is invalid")
    if payload.get("learning_pipeline_mode") != "hybrid_v1_2":
        raise ValueError("Hybrid selection task requires hybrid_v1_2")
    required = {"capture_bundle", "omni_inventory", "gui_actor_selection_input", "target_text", "refinement_policy", "gui_actor_provider_state"}
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"Hybrid selection task payload missing: {', '.join(missing)}")
    if cancellation_event is not None and cancellation_event.is_set():
        return _stopped("cancelled_before_selection")
    origin = payload.get("execution_origin")
    provider_state = payload["gui_actor_provider_state"]
    if origin == "replay":
        if provider_state != "replay_ready":
            return _stopped("gui_actor_provider_not_ready")
    elif origin == "actual_model":
        if actual_execution is None:
            return _stopped("actual_execution_required")
        try:
            validate_actual_execution(payload, actual_execution)
        except ValueError as error:
            return _stopped("actual_execution_invalid:" + str(error))
    else:
        return _stopped("gui_actor_provider_not_ready")
    selection = parse_gui_actor_selection(
        deepcopy(payload["gui_actor_selection_input"]),
        capture_bundle=deepcopy(payload["capture_bundle"]),
        omni_inventory=deepcopy(payload["omni_inventory"]),
        target_text=payload["target_text"],
    )
    vista_input = payload.get("vista_refinement_input")
    if origin == "actual_model" and vista_input is not None:
        try:
            validate_vista_actual_execution(vista_input, refinement_execution)
        except ValueError as error:
            return _stopped("refinement_actual_execution_invalid:" + str(error), selection=selection)
    refinement = resolve_selection_refinement(
        selection=selection, policy=deepcopy(payload["refinement_policy"]),
        inventory=payload["omni_inventory"], vista_refinement_input=vista_input,
    )
    if refinement["status"] == "requested":
        return _stopped("refinement_provider_not_ready", selection=selection, refinement=refinement)
    review = project_selection_review(
        capture_bundle=deepcopy(payload["capture_bundle"]),
        omni_inventory=deepcopy(payload["omni_inventory"]),
        gui_actor_selection_input=deepcopy(payload["gui_actor_selection_input"]),
        target_text=payload["target_text"],
        refinement_policy=deepcopy(payload["refinement_policy"]),
        selection=selection,
        refinement=refinement,
        execution_origin=origin,
        vista_refinement_input=vista_input,
    )
    return {
        "contract_version": "hybrid_selection_task_result_v1",
        "learning_pipeline_mode": "hybrid_v1_2",
        "outcome": "completed",
        "selection": selection,
        "refinement": refinement,
        "review_projection": review,
        "no_live_click_authorization": True,
        "execute_binding_enabled": False,
}


def validate_actual_execution(payload: dict[str, Any], actual_execution: dict[str, Any]) -> dict[str, Any]:
    """校验受信服务器传入的当前模型结果，客户端 payload 不能自证实际来源。"""
    if not isinstance(actual_execution, Mapping) or actual_execution.get("contract_version") != "gui_actor_current_source_result_v1":
        raise ValueError("current_source_result")
    source = actual_execution.get("current_source_receipt")
    if not isinstance(source, Mapping) or source.get("contract_version") != "gui_actor_current_source_receipt_v1" or source.get("source_binding") != "current_source_external_v1":
        raise ValueError("current_source_receipt")
    identities = source.get("code_identity")
    if not isinstance(identities, Mapping) or not identities or not all(isinstance(value, str) and len(value) == 64 for value in identities.values()):
        raise ValueError("current_code_identity")
    selection_input = payload["gui_actor_selection_input"]
    bundle = payload["capture_bundle"]
    if actual_execution.get("provider_id") != selection_input.get("provider_id") or actual_execution.get("raw_output_utf8") != selection_input.get("raw_output_utf8") or actual_execution.get("native_output_ref") != selection_input.get("native_output_ref"):
        raise ValueError("native_output")
    raw = actual_execution.get("raw_output_utf8")
    native_ref = actual_execution.get("native_output_ref")
    if not isinstance(raw, str) or not isinstance(native_ref, Mapping) or native_ref.get("sha256") != sha256(raw.encode("utf-8")).hexdigest():
        raise ValueError("native_output_sha256")
    image_sha = bundle.get("capture_identity", {}).get("screenshot_sha256")
    if actual_execution.get("image_sha256") != image_sha or selection_input.get("image_sha256") != image_sha:
        raise ValueError("image_sha256")
    if actual_execution.get("target_sha256") != sha256(payload["target_text"].encode("utf-8")).hexdigest():
        raise ValueError("target_sha256")
    cleanup = actual_execution.get("cleanup")
    if actual_execution.get("child_exit_code") != 0 or not isinstance(cleanup, Mapping) or cleanup.get("status") != "verified_exact_child_exited" or cleanup.get("exit_code") != 0:
        raise ValueError("child_cleanup")
    if "pid" in actual_execution and actual_execution["pid"] != cleanup.get("pid"):
        raise ValueError("child_pid")
    return deepcopy(dict(actual_execution))


def _stopped(reason: str, *, selection: dict[str, Any] | None = None, refinement: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "contract_version": "hybrid_selection_task_result_v1",
        "learning_pipeline_mode": "hybrid_v1_2",
        "outcome": "safe_stopped",
        "reason": reason,
        "selection": deepcopy(selection),
        "refinement": deepcopy(refinement),
        "review_projection": None,
        "no_live_click_authorization": True,
        "execute_binding_enabled": False,
    }


__all__ = ["run_hybrid_selection_task", "validate_actual_execution"]
