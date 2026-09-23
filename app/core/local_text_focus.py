"""组合输入专用的点击前只读字段绑定；不提供公开输入授权。"""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import get_ident

from app.agent.windows_text_field_reader import probe_local_focus_target
from app.core.local_input_policy import require_local_operator_input


_SCOPE = ContextVar("local_text_focus", default=None)


class LocalTextFocusTarget:
    def __init__(self, handle, pid):
        if any(type(value) is not int or value <= 0 for value in (handle, pid)):
            raise ValueError("invalid local text focus target")
        self.handle, self.pid = handle, pid
        self.binding = None


def check_local_text_focus(point, manager):
    scope = _SCOPE.get()
    if scope is None:
        return None
    if not scope["active"] or scope["owner"] != get_ident() or scope["claimed"]:
        raise ValueError("local text focus scope unavailable")
    target = scope["target"]
    if (type(point) is not dict or set(point) != {"x", "y"}
            or any(type(point[key]) is not int for key in ("x", "y"))):
        raise ValueError("local text focus point invalid")
    require_local_operator_input(manager)
    scope["claimed"] = True
    target.binding = probe_local_focus_target(manager, target.handle, target.pid,
        (point["x"], point["y"]))
    return {"status": "bound", "control_type": target.binding["control_type"],
        "runtime_id": target.binding["runtime_id"]}


@contextmanager
def local_text_focus_scope(target):
    if target is None:
        yield
        return
    if type(target) is not LocalTextFocusTarget or _SCOPE.get() is not None:
        raise ValueError("invalid or overlapping local text focus scope")
    scope = {"target": target, "owner": get_ident(), "active": True, "claimed": False}
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        scope["active"] = False
        _SCOPE.reset(token)
