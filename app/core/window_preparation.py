"""本地人工确认的单次窗口准备许可；不开放键鼠输入或通用窗口变更。"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from threading import Lock
from time import monotonic
from types import MappingProxyType

from app.agent.native_identity import validate_native_identity_fact
from app.core.runtime_input_authority import runtime_backend_input_is_active


_MINT_KEY = object()
_ACTIVE = ContextVar("local_window_preparation", default=None)


def window_preparation_failure_details(error):
    """只公开 Win32 错误事实，不把拒绝访问猜成目标已提权。"""
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        args = getattr(current, "args", ())
        winerror = getattr(current, "winerror", None)
        function = getattr(current, "funcname", None)
        message = getattr(current, "strerror", None)
        if (len(args) == 3 and type(args[0]) is int and isinstance(args[1], str)
                and isinstance(args[2], str)):
            winerror, function, message = args
        if type(winerror) is int:
            return {"winerror": winerror, "win32_function": function if isinstance(function, str) else None,
                    "win32_message": message[:512] if isinstance(message, str) else None,
                    "access_denied": winerror == 5, "target_integrity": "not_measured",
                    "privilege_mismatch_possible": winerror == 5}
        current = current.__cause__ if current.__cause__ is not None else current.__context__
    return {}


def window_preparation_failure_message(details):
    if not details:
        return ""
    message = (f" Win32 error {details['winerror']}"
               f" ({details.get('win32_function') or 'unknown API'}): {details.get('win32_message') or 'unavailable' }.")
    if details["access_denied"]:
        message += (" Access denied; host/target privilege mismatch or Windows access restrictions are possible."
                    " Target integrity was not measured; elevation is not established."
                    " Check the selected process and its permissions; no automatic elevation or retry was performed.")
    return message


class _WindowPreparationPermit:
    __slots__ = ("manager", "identity", "reader", "operations", "expires", "_used", "_lock")

    def __init__(self, key, manager, identity, reader, operation):
        if key is not _MINT_KEY:
            raise PermissionError("local preparation permit cannot be constructed externally")
        if not callable(getattr(reader, "read_identity", None)):
            raise TypeError("local preparation requires a native identity reader")
        if not isinstance(identity, dict):
            raise ValueError("local preparation requires an observed native identity")
        handle = identity.get("target_window_handle")
        checked = validate_native_identity_fact(identity, target_window_handle=handle)
        if checked is None:
            raise ValueError("local preparation identity is invalid")
        if operation not in {"focus", "maximize"}:
            raise ValueError("local preparation operation is invalid")
        operations = frozenset({"focus"}) if operation == "focus" else frozenset({"maximize", "focus"})
        for name, value in (("manager", manager), ("identity", MappingProxyType(deepcopy(checked))),
                            ("reader", reader), ("operations", operations), ("expires", monotonic() + 60),
                            ("_used", False), ("_lock", Lock())):
            object.__setattr__(self, name, value)

    def __setattr__(self, _name, _value):
        raise AttributeError("local preparation permit is immutable")

    def __delattr__(self, _name):
        raise AttributeError("local preparation permit is immutable")

    def verify(self, manager, handle):
        if manager is not self.manager or handle != self.identity["target_window_handle"] or monotonic() >= self.expires:
            raise PermissionError("local preparation target or lifetime changed")
        try:
            current = self.reader.read_identity(handle)
        except Exception as error:
            raise PermissionError("local preparation identity is unavailable") from error
        checked = validate_native_identity_fact(current, target_window_handle=handle)
        if checked != dict(self.identity):
            raise PermissionError("local preparation process identity changed")

    def consume(self, manager):
        with self._lock:
            if self._used:
                raise PermissionError("local preparation permit was already consumed")
            object.__setattr__(self, "_used", True)
        self.verify(manager, self.identity["target_window_handle"])


def _mint_window_preparation_permit(window_manager, identity, identity_reader, *, operation="focus"):
    return _WindowPreparationPermit(_MINT_KEY, window_manager, identity, identity_reader, operation)


@contextmanager
def _window_preparation_scope(permit, manager, *, operation="focus"):
    if type(permit) is not _WindowPreparationPermit or _ACTIVE.get() is not None or runtime_backend_input_is_active():
        raise PermissionError("invalid or overlapping local preparation authority")
    if operation not in permit.operations:
        raise PermissionError("local preparation operation is not allowed")
    permit.consume(manager)
    token = _ACTIVE.set(permit)
    try:
        yield
        permit.verify(manager, permit.identity["target_window_handle"])
    finally:
        _ACTIVE.reset(token)


def _focus_preparation_allowed(manager, handle):
    return _window_preparation_allowed(manager, handle, "focus")


def _window_preparation_allowed(manager, handle, operation):
    permit = _ACTIVE.get()
    if permit is None or handle is None or operation not in permit.operations:
        return False
    permit.verify(manager, handle)
    return True


def _window_preparation_is_active():
    return _ACTIVE.get() is not None
