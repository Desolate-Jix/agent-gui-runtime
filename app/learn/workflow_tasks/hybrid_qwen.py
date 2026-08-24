"""受管 Hybrid Qwen candidate 语义绑定任务。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from app.learn.hybrid.qwen_binding import run_qwen_candidate_binding


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def run_hybrid_qwen_task(
    payload: dict[str, Any],
    *,
    cancellation_event: Any | None = None,
    model_runner: Callable[..., object] | None = None,
    model_releaser: Callable[..., object] | None = None,
) -> dict[str, Any]:
    """注入服务端根目录，并在密封 artifact 后释放既有 Qwen 服务。"""
    if not isinstance(payload, dict) or "project_root" in payload:
        raise ValueError("Hybrid Qwen task payload is invalid")
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
    )
    model_releaser(sealed_artifact=deepcopy(result))
    return result
