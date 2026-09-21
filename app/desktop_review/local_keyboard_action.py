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
    from app.core.input_controller import input_controller, KeyboardForegroundMismatchError
    try:
        result = input_controller.press_key(request.key, x=request.x, y=request.y)
        return APIResponse(success=True, message="Key dispatched", data=result)
    except KeyboardForegroundMismatchError as error:
        # 仅 press_key 的派发前检查可证明本次没有按键；填写路径可能已点击或全选。
        return APIResponse(success=False, message="Key not dispatched: target is not foreground",
            data={"pressed": False, "dispatch_status": "not_dispatched",
                  "diagnostics": dict(error.evidence), "automatic_retry_allowed": False,
                  "next_action": "select_target_and_inspect_before_new_request"},
            error=ErrorModel(code="keyboard_target_not_foreground", details=str(error)))
    except Exception as error:
        return APIResponse(success=False, message="Key dispatch failed; inspect current state before retrying",
            error=ErrorModel(code="key_dispatch_failed", details=str(error)))
