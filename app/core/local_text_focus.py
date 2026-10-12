"""组合输入专用的点击前只读字段绑定；不提供公开输入授权。"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
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
        self.composite_binding = None


class VisualTextFocusTarget(LocalTextFocusTarget):
    """只声明本次视觉点击路线；不伪造 UIA 绑定或授予键盘能力。"""


def has_local_text_focus():
    scope = _SCOPE.get()
    return bool(scope is not None and scope['active'] and scope['owner'] == get_ident()
                 and not scope['claimed'] and type(scope['target']) is LocalTextFocusTarget)


def bind_composite_local_focus_target(resolution, *, image_path, image_size, source_window):
    """只在本次字段范围内冻结同帧子控件；不认请求元数据中的能力或证明。"""
    from PIL import Image
    from app.core.window_manager import window_manager
    from app.core.local_input_policy import current_local_operator_identity
    from app.agent.windows_text_field_reader import TextFieldReadError

    if not has_local_text_focus():
        raise ValueError("composite_field_focus_scope_unavailable")
    target = _SCOPE.get()["target"]
    if target.composite_binding is not None:
        raise ValueError("composite_field_focus_binding_already_set")
    identity = current_local_operator_identity(window_manager)
    bound = window_manager.get_bound_window()
    if (bound is None or bound.handle != target.handle or bound.process_id != target.pid
            or not isinstance(source_window, dict) or source_window.get("handle") != target.handle
            or source_window.get("process_id") != target.pid
            or source_window.get("bbox") != {"x": 0, "y": 0, "w": image_size["width"], "h": image_size["height"]}):
        raise ValueError("composite_field_source_window_changed")
    rect = [bound.rect.left, bound.rect.top, bound.rect.right-bound.rect.left, bound.rect.bottom-bound.rect.top]
    if rect[2:] != [image_size["width"], image_size["height"]]:
        raise ValueError("composite_field_source_geometry_changed")
    path = Path(image_path).resolve()
    source_sha = sha256(path.read_bytes()).hexdigest()
    with Image.open(path) as image:
        if image.size != (image_size["width"], image_size["height"]):
            raise ValueError("composite_field_source_geometry_changed")
    point = tuple(resolution["point"][key] for key in ("x", "y"))
    actual = probe_local_focus_target(window_manager, target.handle, target.pid, point,
        expected_ancestor=resolution["parent"],
        **({"expected_label": target.expected_label} if target.expected_label is not None else {}))
    child = resolution["child"]
    expected = {"runtime_id": child["runtime_id"], "control_type": "Edit",
        "bbox": [child["bbox"][key] for key in ("x", "y", "w", "h")],
        "window_handle": target.handle, "process_id": target.pid,
        "process_create_time": identity["process_create_time"], "window_rect": rect}
    if actual != expected:
        raise TextFieldReadError("text_field_expected_identity_changed")
    current_local_operator_identity(window_manager)
    if sha256(path.read_bytes()).hexdigest() != source_sha:
        raise ValueError("composite_field_source_capture_changed")
    frozen = {"contract_version": "current_composite_field_target_v1", "capture_id": str(path),
        "screenshot_sha256": source_sha, "binding": deepcopy(expected),
        "artifact_is_authorization": False, "action_executed": False}
    target.composite_binding = {**deepcopy(resolution), **deepcopy(frozen)}
    return frozen


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
    if type(target) is VisualTextFocusTarget:
        return {"status": ("compound_replacement_pending" if hasattr(target, "_compound_spec")
            else "postclick_proof_required"), "evidence_kind": "visual"}
    composite = target.composite_binding
    if composite is not None:
        if (point != composite["point"] or sha256(Path(composite["capture_id"]).read_bytes()).hexdigest()
                != composite["screenshot_sha256"]):
            raise ValueError("composite_field_source_or_point_changed")
    actual = probe_local_focus_target(manager, target.handle, target.pid,
        (point["x"], point["y"]),
        **({"expected_ancestor": composite["parent"]} if composite is not None else {}),
        **({"expected_label": target.expected_label} if target.expected_label is not None else {}))
    if composite is not None and actual != composite["binding"]:
        from app.agent.windows_text_field_reader import TextFieldReadError
        raise TextFieldReadError("text_field_expected_identity_changed")
    if composite is not None:
        require_local_operator_input(manager)
        if sha256(Path(composite["capture_id"]).read_bytes()).hexdigest() != composite["screenshot_sha256"]:
            raise ValueError("composite_field_source_capture_changed")
    target.binding = actual
    return {"status": "bound", "control_type": target.binding["control_type"],
        "runtime_id": target.binding["runtime_id"],
        **({"declared_label_verified": True} if target.expected_label is not None else {})}


def revalidate_local_text_focus(point, manager):
    """等待后只读复核原字段，不重新消费范围或更新绑定。"""
    scope = _SCOPE.get()
    if scope is None:
        return None
    if not scope["active"] or scope["owner"] != get_ident() or not scope["claimed"]:
        raise ValueError("local text focus scope unavailable")
    if (type(point) is not dict or set(point) != {"x", "y"}
            or any(type(point[key]) is not int for key in ("x", "y"))):
        raise ValueError("local text focus point invalid")
    target = scope["target"]
    if type(target) is VisualTextFocusTarget:
        require_local_operator_input(manager)
        return {"status": ("compound_replacement_pending" if hasattr(target, "_compound_spec")
            else "postclick_proof_required"), "evidence_kind": "visual"}
    if not isinstance(target.binding, dict):
        raise ValueError("local text focus scope unavailable")
    expected = deepcopy(target.binding)
    composite = deepcopy(target.composite_binding)
    require_local_operator_input(manager)
    if composite is not None:
        if (point != composite["point"] or sha256(Path(composite["capture_id"]).read_bytes()).hexdigest()
                != composite["screenshot_sha256"]):
            raise ValueError("composite_field_source_or_point_changed")
    actual = probe_local_focus_target(manager, target.handle, target.pid,
        (point["x"], point["y"]),
        **({"expected_ancestor": composite["parent"]} if composite is not None else {}),
        **({"expected_label": target.expected_label} if target.expected_label is not None else {}))
    if (actual != expected or target.binding != expected
            or composite is not None and actual != composite["binding"]):
        from app.agent.windows_text_field_reader import TextFieldReadError
        raise TextFieldReadError("text_field_expected_identity_changed")
    require_local_operator_input(manager)
    if composite is not None:
        if sha256(Path(composite["capture_id"]).read_bytes()).hexdigest() != composite["screenshot_sha256"]:
            raise ValueError("composite_field_source_capture_changed")
    if (_SCOPE.get() is not scope or not scope["active"] or scope["owner"] != get_ident()
            or not scope["claimed"]):
        raise ValueError("local text focus scope unavailable")
    return {"status": "revalidated", "control_type": expected["control_type"],
        "runtime_id": deepcopy(expected["runtime_id"]),
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
        target.composite_binding = None
        _SCOPE.reset(token)


@contextmanager
def visual_text_focus_scope(target):
    if type(target) is not VisualTextFocusTarget or _SCOPE.get() is not None:
        raise ValueError("invalid or overlapping visual text focus scope")
    scope = {"target": target, "owner": get_ident(), "active": True, "claimed": False}
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        scope["active"] = False
        _SCOPE.reset(token)
