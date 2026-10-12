"""组合输入的私有焦点字段约束；不授予输入或点击权限，不接受公开 JSON。"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
from threading import get_ident

from app.agent.native_identity import WindowsNativeIdentityReader
from app.agent.text_field_evidence import TextFieldSnapshot
from app.agent.windows_text_field_reader import WindowsTextFieldReader, _contains_point, _within_focus_edge_rounding
from app.core.local_input_policy import require_local_operator_input
from app.core.visual_compound_input import VisualCompoundKeyboardTarget


_SCOPE = ContextVar("local_keyboard_target", default=None)
_VISUAL_ISSUER = object()


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
        # 仅私有焦点绑定接受同实例的单像素边缘舍入，原锚点仍须在当前字段内。
        identity_matches = type(current) is TextFieldSnapshot and (current.identity == identity or self.focus_reflow
            and current.identity.window_rect == identity.window_rect
            and replace(current.identity, control_bbox=identity.control_bbox) == identity
            and _within_focus_edge_rounding(current.identity.control_bbox, identity.control_bbox)
            and _contains_point(current.identity.control_bbox, self.point))
        if (type(current) is not TextFieldSnapshot or not identity_matches
                or current.value != before.value or current.source != before.source
                or self.operation == "type_text" and not self.clear_existing and current.selection != before.selection
                or not require_local_operator_input(manager)):
            raise ValueError("internal keyboard field changed")


@dataclass(frozen=True, slots=True)
class VisualKeyboardTarget:
    proof: object = field(repr=False)
    operation: str
    text_sha256: str | None = None
    clear_existing: bool = False
    submit_search: bool = False
    _issuer: object = field(default=None, repr=False)
    _field_json: str = field(init=False, repr=False)
    _consumed: bool = field(default=False, init=False, repr=False)
    _selection_dispatch: object = field(default=None, init=False, repr=False)
    _selection_reviewer: object = field(default=None, repr=False)
    _selection_checked: bool = field(default=False, init=False, repr=False)
    _selection_proof: object = field(default=None, init=False, repr=False)
    _freshness_reviewer: object = field(default=None, repr=False)
    _freshness_checked: bool = field(default=False, init=False, repr=False)
    _freshness_proof: object = field(default=None, init=False, repr=False)

    def __post_init__(self):
        from app.execution.visual_field_proof import _checked_proof, visual_field_is_empty
        if self._issuer is not _VISUAL_ISSUER:
            raise ValueError("visual keyboard issuer unavailable")
        action = _checked_proof(self.proof)["request"]["action"]
        expected = action["field"]
        if self.operation == "type_text":
            if (action["field_phase"] != "focus" or type(self.clear_existing) is not bool
                    or not self.clear_existing and not visual_field_is_empty(self.proof)
                    or self.submit_search is not False
                    or self.text_sha256 != sha256(expected["expected_text"].encode("utf-8")).hexdigest()):
                raise ValueError("visual keyboard replacement binding invalid")
        elif self.operation == "press_key":
            if (action["field_phase"] != "value" or self.submit_search is not True
                    or expected["field_kind"] not in {"search", "address_bar"}
                    or self.text_sha256 is not None or self.clear_existing is not False):
                raise ValueError("visual keyboard search binding invalid")
        else:
            raise ValueError("visual keyboard operation unsupported")
        object.__setattr__(self, "_field_json", json.dumps(expected, ensure_ascii=False, allow_nan=False))

    @property
    def window_identity(self):
        return json.loads(self._field_json)["window_identity"]

    @property
    def window_rect(self):
        return tuple(json.loads(self._field_json)["window_rect"])

    @property
    def point(self):
        point = json.loads(self._field_json)["click_point"]
        return point["x"], point["y"]

    def validate_command(self, operation, request):
        if (operation != self.operation or (request.get("x"), request.get("y")) != self.point
                or any(type(request.get(k)) is not int for k in ("x", "y"))):
            raise ValueError("visual keyboard command changed")
        if operation == "type_text":
            if (type(request.get("text")) is not str
                    or sha256(request["text"].encode("utf-8")).hexdigest() != self.text_sha256
                    or request.get("clear_existing", False) is not self.clear_existing
                    or request.get("click_before_typing", False) is not False
                    or request.get("submit", False) is not False):
                raise ValueError("visual keyboard command changed")
        elif request.get("key") != "Enter":
            raise ValueError("visual keyboard search key changed")

    def record_selection(self, dispatch):
        from pathlib import Path
        from app.core.typing_dispatch import TypingDispatchReceipt
        scope = _checked_scope()
        if (scope["target"] is not self or not scope["claimed"] or self._selection_dispatch is not None
                or type(dispatch) is not TypingDispatchReceipt or self.operation != "type_text" or not self.clear_existing):
            raise ValueError("visual keyboard selection scope unavailable")
        dispatch.persist_selection(Path(self.proof._service.session_dir) / "visual-field-proof" / "typing-dispatch")
        object.__setattr__(self, "_selection_dispatch", dispatch)

    def verify(self, manager):
        from app.execution.visual_field_proof import (revalidate_visual_field, verify_visual_selection,
            verify_visual_field_freshness, VisualFieldChanged)
        scope = _checked_scope()
        if scope["target"] is not self or not scope["claimed"] or self._issuer is not _VISUAL_ISSUER:
            raise ValueError("visual keyboard scope unavailable")
        if self._freshness_checked and self._freshness_proof is None:
            raise ValueError("visual keyboard freshness review not adopted")
        from app.execution.visual_field_proof import _checked_proof
        from app.judgment.visual_action_conditions import VISUAL_INPUT_CLICKED_CONDITION
        if _checked_proof(self.proof)["request"]["condition"] == VISUAL_INPUT_CLICKED_CONDITION:
            # 新默认路线只核对真实全选派发，不重复询问空框或选区语义。
            if self._selection_dispatch is not None:
                dispatch = self._selection_dispatch.reference()
                if (dispatch["selection_dispatch"] != "completed" or dispatch["text_dispatch"] != "not_started"
                        or dispatch["submit_dispatch"] != "not_started"):
                    raise ValueError("visual keyboard selection dispatch invalid")
            revalidate_visual_field(self.proof, manager)
            return
        try:
            revalidate_visual_field(self._selection_proof or self._freshness_proof or self.proof, manager,
                selection_pending=self._selection_dispatch is not None and not self._selection_checked)
        except VisualFieldChanged as error:
            if self._selection_dispatch is not None:
                if self._selection_checked:
                    raise
                object.__setattr__(self, "_selection_checked", True)
                selected = verify_visual_selection(self.proof, manager, self._selection_dispatch, self._selection_reviewer,
                    frame=error.frame, native_snapshot=error.native_snapshot)
                object.__setattr__(self, "_selection_proof", selected)
            else:
                if self._freshness_checked or self._freshness_reviewer is None or error.native_snapshot is None:
                    raise
                object.__setattr__(self, "_freshness_checked", True)
                reviewed = self._freshness_reviewer(self.proof, error.frame, error.native_snapshot)
                reviewed = verify_visual_field_freshness(self.proof, reviewed, manager,
                    frame=error.frame, native_snapshot=error.native_snapshot)
                object.__setattr__(self, "_freshness_proof", reviewed)


def issue_visual_keyboard_target(proof, operation, *, text=None, clear_existing=True, submit_search=False,
                                selection_reviewer=None, freshness_reviewer=None):
    from app.execution.visual_field_proof import _claim_keyboard_proof
    if operation == "type_text" and type(text) is not str:
        raise ValueError("visual keyboard text binding unavailable")
    if selection_reviewer is not None and (operation != "type_text" or not callable(selection_reviewer)):
        raise ValueError("visual keyboard selection reviewer invalid")
    if freshness_reviewer is not None and not callable(freshness_reviewer):
        raise ValueError("visual keyboard freshness reviewer invalid")
    target = VisualKeyboardTarget(proof, operation,
        text_sha256=sha256(text.encode("utf-8")).hexdigest() if text is not None else None,
        clear_existing=clear_existing if operation == "type_text" else False,
        submit_search=submit_search, _issuer=_VISUAL_ISSUER, _selection_reviewer=selection_reviewer,
        _freshness_reviewer=freshness_reviewer)
    _claim_keyboard_proof(proof)
    return target


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
    if type(target) in {VisualKeyboardTarget, VisualCompoundKeyboardTarget}:
        if target._consumed:
            raise ValueError("visual keyboard target already consumed")
        object.__setattr__(target, "_consumed", True)
    scope["claimed"] = True
    return target


@contextmanager
def local_keyboard_target_scope(target):
    if target is None:
        yield
        return
    if type(target) not in {LocalKeyboardTarget, VisualKeyboardTarget, VisualCompoundKeyboardTarget} or _SCOPE.get() is not None:
        raise ValueError("invalid or overlapping internal keyboard scope")
    if type(target) in {VisualKeyboardTarget, VisualCompoundKeyboardTarget} and target._consumed:
        raise ValueError("visual keyboard target already consumed")
    scope = {"target": target, "owner": get_ident(), "active": True, "claimed": False}
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        # 复制到其它 Context 的引用也同时失效。
        scope["active"] = False
        _SCOPE.reset(token)
