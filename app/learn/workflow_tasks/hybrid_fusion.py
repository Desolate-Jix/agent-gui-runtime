"""受管 Hybrid 决定性融合任务。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.learn.hybrid.fusion import fuse_hybrid_candidates


_REQUIRED_INPUTS = (
    "config",
    "capture_bundle",
    "omni_inventory",
    "qwen_bindings",
)


def run_hybrid_fusion_task(
    payload: dict[str, Any],
    *,
    cancellation_event: Any | None = None,
) -> dict[str, Any]:
    """执行无 provider、无 GUI、无动作权限的纯融合。"""
    if not isinstance(payload, dict) or "project_root" in payload:
        raise ValueError("Hybrid fusion task payload is invalid")
    missing = [field for field in _REQUIRED_INPUTS if field not in payload]
    if missing:
        raise ValueError(f"Hybrid fusion task payload missing: {', '.join(missing)}")
    if cancellation_event is not None and cancellation_event.is_set():
        raise ValueError("Hybrid fusion task cancelled")
    return fuse_hybrid_candidates(
        config=deepcopy(payload["config"]),
        capture_bundle=deepcopy(payload["capture_bundle"]),
        omni_inventory=deepcopy(payload["omni_inventory"]),
        qwen_bindings=deepcopy(payload["qwen_bindings"]),
    )


__all__ = ["run_hybrid_fusion_task"]
