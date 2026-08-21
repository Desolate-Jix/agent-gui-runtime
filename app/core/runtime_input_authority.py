"""进程内 Windows 输入放行状态；只供内部 DesktopBackend 使用。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


_RUNTIME_BACKEND_INPUT_ACTIVE: ContextVar[bool] = ContextVar(
    "runtime_backend_input_active",
    default=False,
)


def runtime_backend_input_is_active() -> bool:
    return _RUNTIME_BACKEND_INPUT_ACTIVE.get()


@contextmanager
def _runtime_backend_input_scope() -> Iterator[None]:
    """在 one-shot authority 已消费后短时放行底层 Windows 输入。"""

    token = _RUNTIME_BACKEND_INPUT_ACTIVE.set(True)
    try:
        yield
    finally:
        _RUNTIME_BACKEND_INPUT_ACTIVE.reset(token)


__all__ = ["runtime_backend_input_is_active"]
