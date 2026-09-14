"""本地无学习回车适配，不新增网络授权或通用系统快捷键。"""
from typing import Literal
from pydantic import BaseModel, Field

from app.api.models.request import ROIModel
from app.api.models.response import APIResponse, ErrorModel


class LocalKeyRequest(BaseModel):
    key: Literal["Enter"]
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
