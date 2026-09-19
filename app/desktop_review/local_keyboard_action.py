"""本地无学习编辑键适配，复用现有键盘后端。"""
from pydantic import BaseModel, Field

from app.api.models.request import ROIModel
from app.api.models.response import APIResponse, ErrorModel
from app.core.editing_keys import EditingKey


class LocalKeyRequest(BaseModel):
    key: EditingKey
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    capture_roi: ROIModel | None = None


def press_local_key(request: LocalKeyRequest) -> APIResponse:
    from app.core.input_controller import input_controller
    try:
        result = input_controller.press_key(request.key, x=request.x, y=request.y)
        return APIResponse(success=True, message="Key dispatched", data=result)
    except Exception as error:
        return APIResponse(success=False, message="Key dispatch failed; inspect current state before retrying",
            error=ErrorModel(code="key_dispatch_failed", details=str(error)))
