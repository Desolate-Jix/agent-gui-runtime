"""组合输入专用的点击前只读字段绑定；不提供公开输入授权。"""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import get_ident

from app.agent.windows_text_field_reader import probe_local_focus_target
from app.core.local_input_policy import require_local_operator_input


_SCOPE = ContextVar("local_text_focus", default=None)


class LocalTextFocusTarget:
    def __init__(self, handle, pid, *, expected_label=None):
        if any(type(value) is not int or value <= 0 for value in (handle, pid)):
            raise ValueError("invalid local text focus target")
        self.handle, self.pid = handle, pid
        if expected_label is not None and (not isinstance(expected_label, str) or not expected_label.strip()):
            raise ValueError("invalid local text focus label")
        self.expected_label = expected_label
        self.binding = None


def has_local_text_focus():
    scope = _SCOPE.get()
    return bool(scope is not None and scope['active'] and scope['owner'] == get_ident()
                and not scope['claimed'])


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
        (point["x"], point["y"]),
        **({"expected_label": target.expected_label} if target.expected_label is not None else {}))
    return {"status": "bound", "control_type": target.binding["control_type"],
        "runtime_id": target.binding["runtime_id"],
        **({"declared_label_verified": True} if target.expected_label is not None else {})}


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
