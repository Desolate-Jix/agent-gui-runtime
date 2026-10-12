"""原按键调用的私有派发前沿；公开结构不能冒充同次内部回执。"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from threading import get_ident
from time import perf_counter_ns


_ISSUER = object()
_SCOPE = ContextVar('key_dispatch_receipt', default=None)


@contextmanager
def key_dispatch_scope():
    token = _SCOPE.set((_ISSUER, object(), get_ident()))
    try:
        yield
    finally:
        _SCOPE.reset(token)


class KeyDispatchReceipt:
    def __init__(self, key, x, y, *, _issuer):
        if _issuer is not _ISSUER:
            raise ValueError('key dispatch issuer unavailable')
        self._issuer, self._owner, self._scope = _issuer, get_ident(), _SCOPE.get()
        self._key, self._point = key, {'x': x, 'y': y}
        self._state, self._events, self._started = 'not_started', [], perf_counter_ns()

    def _check(self):
        if self._issuer is not _ISSUER or self._owner != get_ident():
            raise ValueError('key dispatch owner unavailable')

    def record(self, status):
        self._check()
        expected = 'not_started' if status == 'started' else 'started' if status == 'completed' else None
        if self._state != expected:
            raise ValueError('key dispatch transition invalid')
        self._state = status
        self._events.append({'status': status, 'elapsed_ms': (perf_counter_ns() - self._started) / 1_000_000})

    def reference(self):
        self._check()
        return {'schema': 'key_dispatch.v1', 'key': self._key, 'point': dict(self._point),
            'dispatch': self._state, 'input_started': self._state != 'not_started',
            'action_executed': True if self._state == 'completed' else None if self._state == 'started' else False,
            'events': deepcopy(self._events), 'artifact_is_authorization': False}

    def __enter__(self):
        self._check()
        return self

    def __exit__(self, kind, error, traceback):
        if error is not None:
            error._key_dispatch_receipt = self


def create_key_dispatch(key, x, y):
    return KeyDispatchReceipt(key, x, y, _issuer=_ISSUER)


def key_dispatch_from_error(error):
    receipt, scope = getattr(error, '_key_dispatch_receipt', None), _SCOPE.get()
    return (receipt.reference() if type(receipt) is KeyDispatchReceipt and scope is not None
        and receipt._scope is scope and scope[2] == get_ident() else None)
