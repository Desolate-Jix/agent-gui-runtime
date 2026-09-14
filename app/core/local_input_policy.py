"""本地关闭安全策略时的短时输入范围；不改变严格后端授权或全局默认值。"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from threading import Lock, get_ident

from app.agent.native_identity import validate_native_identity_fact


_LOCAL_INPUT_POLICY = ContextVar("local_operator_input_policy", default=None)
_LOCAL_STEP_LOCK = Lock()


@contextmanager
def _local_operator_step_scope():
    # 各协调器共用桌面与窗口管理器，必须在绑定和截图之前排除并发单步。
    if not _LOCAL_STEP_LOCK.acquire(blocking=False):
        raise PermissionError("another local step is already using the desktop")
    try:
        yield
    finally:
        _LOCAL_STEP_LOCK.release()


def _window_rect(bound):
    rect = bound.rect
    return (rect.left, rect.top, rect.right, rect.bottom)


def local_operator_input_is_allowed(manager) -> bool:
    scope = _LOCAL_INPUT_POLICY.get()
    if scope is None or not scope["active"] or scope["manager"] is not manager or scope["owner_thread"] != get_ident():
        return False
    if not scope["enabled"]():
        return False
    try:
        identity = scope["identity"]
        bound = manager.get_bound_window()
        if bound is None or bound.handle != identity["target_window_handle"] or bound.process_id != identity["process_id"]:
            return False
        if _window_rect(bound) != scope["window_rect"]:
            return False
        current = scope["reader"].read_identity(bound.handle)
        checked = validate_native_identity_fact(current, target_window_handle=bound.handle,
                                                expected_process_id=bound.process_id)
        return checked == identity
    except Exception:
        # 身份读取失败不产生额外输入许可。
        return False


def require_local_operator_input(manager) -> bool:
    scope = _LOCAL_INPUT_POLICY.get()
    if scope is None or not scope["active"]:
        return False
    if not local_operator_input_is_allowed(manager):
        raise PermissionError("local safety-off input is unavailable: target identity/geometry changed, wrong owner, or step cancelled")
    return True


@contextmanager
def _local_operator_input_scope(*, manager, identity_reader, identity, window_rect, enabled):
    if _LOCAL_INPUT_POLICY.get() is not None:
        raise PermissionError("local operator input scopes cannot overlap")
    checked = validate_native_identity_fact(identity, target_window_handle=identity.get("target_window_handle"))
    if checked is None or not callable(enabled) or not enabled():
        raise PermissionError("local operator input requires the disabled session safety policy")
    scope = {"manager": manager, "reader": identity_reader, "identity": deepcopy(checked),
             "window_rect": tuple(window_rect), "owner_thread": get_ident(), "enabled": enabled, "active": True}
    token = _LOCAL_INPUT_POLICY.set(scope)
    try:
        if not local_operator_input_is_allowed(manager):
            raise PermissionError("local operator target identity or geometry changed")
        yield
    finally:
        # 同时撤销复制出去的 Context，不能只恢复当前线程的 ContextVar。
        scope["active"] = False
        _LOCAL_INPUT_POLICY.reset(token)
