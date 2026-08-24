"""Hybrid Omni discovery 的受管 workflow adapter。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from threading import Event
from typing import Any

from app.learn.hybrid.omni_discovery import run_hybrid_omni_discovery


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def run_hybrid_omni_task(
    payload: dict[str, Any],
    *,
    cancellation_event: Event | None = None,
) -> dict[str, Any]:
    """在调用 discovery 前由服务端绑定文件系统 authority。"""
    if not isinstance(payload, dict) or "project_root" in payload:
        raise ValueError("managed Hybrid Omni payload must not set project_root")
    request = deepcopy(payload)
    request["project_root"] = str(_PROJECT_ROOT)
    return run_hybrid_omni_discovery(
        request,
        cancellation_event=cancellation_event,
    )
