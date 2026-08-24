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
) -> dict[str, Any]:
    """注入服务端根目录，并在密封 artifact 后释放既有 Qwen 服务。"""
    validate_hybrid_qwen_task_payload(payload)
    if model_runner is None or model_releaser is None:
        from app.core.model_server import (
            release_qwen_model_server,
            run_qwen_binding_model,
        )

        model_runner = model_runner or run_qwen_binding_model
        model_releaser = model_releaser or release_qwen_model_server
    result = run_qwen_candidate_binding(
        {**deepcopy(payload), "project_root": str(_PROJECT_ROOT)},
        model_runner=model_runner,
        cancellation_event=cancellation_event,
        model_lease=deepcopy(model_lease),
    )
    model_releaser(
        sealed_artifact=deepcopy(result),
        omni_inventory=deepcopy(payload.get("omni_inventory")),
        model_lease=deepcopy(model_lease),
    )
    return result
