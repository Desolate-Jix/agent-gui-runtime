"""本地无学习编辑键适配，复用现有键盘后端。"""
from app.execution.local_action_contract import LocalKeyRequest

from app.api.models.response import APIResponse, ErrorModel


def press_local_key(request: LocalKeyRequest) -> APIResponse:
    from app.core.key_dispatch import key_dispatch_scope
    with key_dispatch_scope():
        return _press_local_key(request)


def _press_local_key(request: LocalKeyRequest) -> APIResponse:
    from app.core.input_controller import input_controller, KeyboardForegroundMismatchError
    from app.core.key_dispatch import key_dispatch_from_error
    try:
        result = input_controller.press_key(request.key, x=request.x, y=request.y)
        return APIResponse(success=True, message="Key dispatched", data=result)
    except Exception as error:
        dispatch = key_dispatch_from_error(error)
        if (dispatch is not None and dispatch['dispatch'] == 'not_started'
                and dispatch['key'] == request.key and dispatch['point'] == {'x': request.x, 'y': request.y}):
            data = {'contract_version': 'press_key_result_v1', 'pressed': False,
                'key': request.key, 'point': {'x': request.x, 'y': request.y}, 'input_started': False,
                'dispatch_status': 'not_dispatched', 'key_dispatch': dispatch, 'automatic_retry_allowed': False}
            if isinstance(error, KeyboardForegroundMismatchError):
                data.update(diagnostics=dict(error.evidence),
                    next_action='select_target_and_inspect_before_new_request')
                return APIResponse(success=False, message="Key not dispatched: target is not foreground", data=data,
                    error=ErrorModel(code="keyboard_target_not_foreground", details=str(error)))
            return APIResponse(success=False, message='Key not dispatched: input precheck rejected', data=data,
                error=ErrorModel(code='key_dispatch_failed', details=str(error)))
        return APIResponse(success=False, message="Key dispatch failed; inspect current state before retrying",
            error=ErrorModel(code="key_dispatch_failed", details=str(error)))
