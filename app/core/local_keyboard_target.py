"""组合输入的私有焦点字段约束；不授予输入或点击权限，不接受公开 JSON。"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from hashlib import sha256
from threading import get_ident

from app.agent.native_identity import WindowsNativeIdentityReader
from app.agent.text_field_evidence import TextFieldSnapshot
from app.agent.windows_text_field_reader import WindowsTextFieldReader
from app.core.local_input_policy import require_local_operator_input


_SCOPE = ContextVar("local_keyboard_target", default=None)


@dataclass(frozen=True, slots=True)
class LocalKeyboardTarget:
    snapshot: TextFieldSnapshot = field(repr=False)
    control_type: str
    point: tuple[int, int]
    operation: str
    text_sha256: str | None = None
    clear_existing: bool = False
    focus_reflow: bool = False
    key: str = "Enter"

    def __post_init__(self):
        if (type(self.snapshot) is not TextFieldSnapshot
                or self.control_type not in ({"Edit", "ComboBox", "Document", "Group"}
                    if self.focus_reflow else {"Edit", "ComboBox"})
                or type(self.point) is not tuple or len(self.point) != 2
                or any(type(v) is not int for v in self.point) or type(self.clear_existing) is not bool
                or type(self.focus_reflow) is not bool
                or type(self.key) is not str or self.key not in {"Enter", "Tab"}
                or self.operation not in {"type_text", "press_key"}):
            raise ValueError("invalid internal keyboard field target")
        x, y, w, h = self.snapshot.identity.control_bbox
        if not (x <= self.point[0] < x+w and y <= self.point[1] < y+h):
            raise ValueError("internal keyboard point is outside the bound field")
        if self.operation == "type_text":
            if (type(self.text_sha256) is not str or len(self.text_sha256) != 64
                    or any(c not in "0123456789abcdef" for c in self.text_sha256)):
                raise ValueError("internal keyboard text binding unavailable")
        elif self.text_sha256 is not None or self.clear_existing:
            raise ValueError("internal key binding is invalid")

    def validate_command(self, operation, request):
        if (operation != self.operation or (request.get("x"), request.get("y")) != self.point
                or any(type(request.get(k)) is not int for k in ("x", "y"))):
            raise ValueError("internal keyboard command changed")
        if operation == "type_text":
            if (type(request.get("text")) is not str
                    or sha256(request["text"].encode("utf-8")).hexdigest() != self.text_sha256
                    or request.get("clear_existing", False) is not self.clear_existing
                    or request.get("click_before_typing", False) is not False
                    or request.get("submit", False) is not False):
                raise ValueError("internal keyboard command changed")
        elif request.get("key") != self.key:
            raise ValueError("internal keyboard command changed")

    def verify(self, manager):
        scope = _checked_scope()
        if scope["target"] is not self or not scope["claimed"] or not require_local_operator_input(manager):
            raise ValueError("internal keyboard scope unavailable")
        before = self.snapshot
        identity = before.identity
        reader = WindowsTextFieldReader(window_manager=manager,
            native_identity_reader=WindowsNativeIdentityReader(window_manager=manager))
        common = {"target_field_id": identity.target_field_id, "capture_id": before.capture_id,
            "target_window_handle": identity.window_handle, "target_process_id": identity.process_id,
            "process_create_time": identity.process_create_time, "window_rect": identity.window_rect,
            "expected_runtime_id": identity.runtime_id, "expected_control_type": self.control_type}
        current = (reader.read_bound_focus(**common) if self.focus_reflow else reader.read_field(
            **common, target_bbox=identity.control_bbox, click_point=self.point,
            require_keyboard_focus=True))
        if (type(current) is not TextFieldSnapshot or current.identity != identity
                or current.value != before.value or current.source != before.source
                or self.operation == "type_text" and not self.clear_existing and current.selection != before.selection
                or not require_local_operator_input(manager)):
            raise ValueError("internal keyboard field changed")


def _checked_scope():
    scope = _SCOPE.get()
    if scope is None or not scope["active"] or scope["owner"] != get_ident():
        raise ValueError("internal keyboard scope unavailable")
    return scope


def claim_keyboard_target(operation, request):
    if _SCOPE.get() is None:
        return None
    scope = _checked_scope()
    if scope["claimed"]:
        raise ValueError("internal keyboard scope already consumed")
    target = scope["target"]
    target.validate_command(operation, request)
    scope["claimed"] = True
    return target


@contextmanager
def local_keyboard_target_scope(target):
    if target is None:
        yield
        return
    if type(target) is not LocalKeyboardTarget or _SCOPE.get() is not None:
        raise ValueError("invalid or overlapping internal keyboard scope")
    scope = {"target": target, "owner": get_ident(), "active": True, "claimed": False}
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        # 复制到其它 Context 的引用也同时失效。
        scope["active"] = False
        _SCOPE.reset(token)
