"""为首次学习观察构造隔离的被动依赖。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from app.agent.fresh_learning_observation import FreshLearningObservationOwner
from app.agent.native_identity import WindowsNativeIdentityReader
from app.agent.windows_uia_origin_reader import WindowsUIAOriginReader
from app.core.screenshot import ScreenshotService
from app.core.window_manager import WindowManager
from app.operation.screen_reading.uia_provider import uia_provider


def create_fresh_learning_observation_owner(
    *,
    project_root: str | Path,
    application_identity: Mapping[str, Any],
    target_window_handle: int,
    target_process_id: int,
    vision_configuration=None,
) -> FreshLearningObservationOwner:
    """被动绑定一个明确窗口，不聚焦也不改动共享绑定。"""

    if isinstance(target_window_handle, bool) or not isinstance(target_window_handle, int) or target_window_handle < 1:
        raise ValueError("target window handle must be a positive integer")
    if isinstance(target_process_id, bool) or not isinstance(target_process_id, int) or target_process_id < 1:
        raise ValueError("target process ID must be a positive integer")
    root = Path(project_root).resolve()
    manager = WindowManager()
    bound = manager.bind_window_by_handle(target_window_handle)
    if getattr(bound, "handle", None) != target_window_handle:
        raise ValueError("bound window handle does not match the requested target")
    if getattr(bound, "process_id", None) != target_process_id:
        raise ValueError("bound window process ID does not match the requested target")
    return FreshLearningObservationOwner(
        project_root=root,
        application_identity=application_identity,
        screenshot_service=ScreenshotService(
            window_manager=manager,
            capture_dir=root / "runtime_state" / "fresh-learning-captures",
        ),
        window_manager=manager,
        native_identity_reader=WindowsNativeIdentityReader(window_manager=manager),
        origin_reader=WindowsUIAOriginReader(window_manager=manager),
        uia_provider=uia_provider,
        vision_configuration=vision_configuration,
    )


__all__ = ["create_fresh_learning_observation_owner"]
