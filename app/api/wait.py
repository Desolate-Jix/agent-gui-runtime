from __future__ import annotations

from fastapi import APIRouter

from app.core.scene_detector import scene_detector
from app.models.request import WaitForSceneRequest
from app.models.response import APIResponse, WaitResultData

router = APIRouter(prefix="/wait", tags=["wait"])


@router.post("/scene", response_model=APIResponse)
def wait_for_scene(request: WaitForSceneRequest) -> APIResponse:
    """Wait for a named scene to appear."""
    result = scene_detector.wait_for_scene(request.scene_name, request.timeout)
    data = WaitResultData(**result)
    return APIResponse(success=True, message="Scene wait completed", data=data.model_dump(), error=None)
