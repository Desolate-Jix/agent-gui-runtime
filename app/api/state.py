from __future__ import annotations

from fastapi import APIRouter

from app.core.scene_detector import scene_detector
from app.core.screenshot import screenshot_service
from app.core.window_manager import window_manager
from app.models.request import CaptureWindowRequest
from app.models.response import APIResponse, CaptureData, ErrorModel, StateData, WindowRectModel

router = APIRouter(tags=["state"])


@router.get("/state", response_model=APIResponse)
def get_state() -> APIResponse:
    """Return high-level runtime state for the currently bound session."""
    bound = window_manager.get_bound_window()
    scene = scene_detector.detect_scene()

    if bound is None:
        data = StateData(bound=False, is_active=False, scene_name=scene.get("scene_name"))
    else:
        data = StateData(
            bound=True,
            handle=bound.handle,
            window_title=bound.title,
            process_id=bound.process_id,
            process_name=bound.process_name,
            rect=WindowRectModel(
                left=bound.rect.left,
                top=bound.rect.top,
                right=bound.rect.right,
                bottom=bound.rect.bottom,
            ),
            is_active=bound.is_active,
            scene_name=scene.get("scene_name"),
        )

    return APIResponse(success=True, message="State retrieved", data=data.model_dump(), error=None)


@router.post("/state/capture_window", response_model=APIResponse)
def capture_window(request: CaptureWindowRequest) -> APIResponse:
    """Capture a real screenshot of the currently bound window."""
    try:
        result = screenshot_service.capture_window(roi=request.roi, save_image=request.save_image)
        data = CaptureData(**result)
        return APIResponse(success=True, message="Window captured", data=data.model_dump(), error=None)
    except ValueError as exc:
        return APIResponse(
            success=False,
            message="Capture failed",
            data=None,
            error=ErrorModel(code="capture_failed", details=str(exc)),
        )
