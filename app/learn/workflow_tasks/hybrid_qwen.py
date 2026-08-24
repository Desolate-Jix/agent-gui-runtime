"""受管 Hybrid Qwen candidate 语义绑定任务。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from app.learn.hybrid.qwen_binding import (
    run_qwen_candidate_binding,
    validate_sealed_omni_inventory,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def validate_hybrid_qwen_task_payload(payload: object) -> None:
    """在服务获取前关闭客户端根目录和未密封 Omni 输入。"""
    if not isinstance(payload, dict) or "project_root" in payload:
        raise ValueError("Hybrid Qwen task payload is invalid")
    validate_sealed_omni_inventory(payload.get("omni_inventory"))


def run_hybrid_qwen_task(
    payload: dict[str, Any],
    *,
    cancellation_event: Any | None = None,
    model_runner: Callable[..., object] | None = None,
    model_releaser: Callable[..., object] | None = None,
    model_lease: dict[str, Any] | None = None,
    model_failure_reconciler: Callable[..., object] | None = None,
) -> dict[str, Any]:
    """注入服务端根目录，并在密封 artifact 后释放既有 Qwen 服务。"""
    validate_hybrid_qwen_task_payload(payload)
    if model_runner is None or model_releaser is None or model_failure_reconciler is None:
        from app.core.model_server import (
            reconcile_qwen_model_lease_failure,
            release_qwen_model_server,
            run_qwen_binding_model,
        )

        model_runner = model_runner or run_qwen_binding_model
        model_releaser = model_releaser or release_qwen_model_server
        model_failure_reconciler = (
            model_failure_reconciler or reconcile_qwen_model_lease_failure
        )
    compute_completed = False

    def mark_compute_completed() -> None:
        nonlocal compute_completed
        compute_completed = True

    try:
        result = run_qwen_candidate_binding(
            {**deepcopy(payload), "project_root": str(_PROJECT_ROOT)},
            model_runner=model_runner,
            cancellation_event=cancellation_event,
            model_lease=deepcopy(model_lease),
            model_completion_notifier=mark_compute_completed,
        )
    except BaseException as error:
        message = str(error)
        if error.__class__.__name__ == "QwenBindingTimeout":
            reason = "timeout"
        elif "invalid JSON" in message:
            reason = "invalid_json"
        else:
            reason = "parser_rejection"
        _reconcile_failure_without_masking(
            error,
            reconciler=model_failure_reconciler,
            model_lease=model_lease,
            compute_completed=compute_completed,
            reason=reason,
        )
        raise
    try:
        model_releaser(
            sealed_artifact=deepcopy(result),
            omni_inventory=deepcopy(payload.get("omni_inventory")),
            model_lease=deepcopy(model_lease),
        )
    except BaseException as error:
        _reconcile_failure_without_masking(
            error,
            reconciler=model_failure_reconciler,
            model_lease=model_lease,
            compute_completed=True,
            reason="release_failure",
        )
        raise
    return result


def _reconcile_failure_without_masking(
    error: BaseException,
    *,
    reconciler: Callable[..., object],
    model_lease: dict[str, Any] | None,
    compute_completed: bool,
    reason: str,
) -> None:
    if model_lease is None:
        return
    try:
        reconciler(
            model_lease=deepcopy(model_lease),
            compute_completed=compute_completed,
            reason=reason,
        )
    except BaseException as cleanup_error:
        error.add_note(f"Qwen lease reconciliation remained pending: {cleanup_error}")
