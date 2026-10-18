"""原生单步 Runtime 的惰性串行线程所有者。"""

from __future__ import annotations

from concurrent.futures import Future
from contextlib import ExitStack
from pathlib import Path
from queue import Queue
from threading import Lock, Thread, current_thread, get_ident
from typing import Any, Callable, ContextManager


class RuntimeOwnerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


_STOP = object()


class SerialRuntimeOwner:
    """首次调用时启动，并把所有 Runtime 调用固定到同一线程。"""

    def __init__(
        self,
        *,
        initializer: Callable[[], None] | None = None,
        finalizer: Callable[[], None] | None = None,
        output_root: str | Path | None = None,
        call_scope: Callable[[], ContextManager[Any]] | None = None,
    ) -> None:
        self._output_root = None if output_root is None else Path(output_root).expanduser().resolve()
        self._call_scope = call_scope
        self._initializer = initializer or _initialize_com
        self._finalizer = finalizer or _finalize_com
        self._queue: Queue[Any] = Queue()
        self._guard = Lock()
        self._thread: Thread | None = None
        self._closed = False
        self._thread_id: int | None = None
        self._terminal_error: BaseException | None = None

    @property
    def thread_id(self) -> int | None:
        return self._thread_id

    def call(self, function: Callable[[], Any]) -> Any:
        if not callable(function):
            raise TypeError("function must be callable")
        with self._guard:
            if self._closed:
                raise RuntimeOwnerError("runtime_owner_closed", "runtime owner is closed")
            inline = current_thread() is self._thread
            if not inline and self._thread is None:
                self._thread = Thread(
                    target=self._run,
                    name="native-single-step-runtime-owner",
                    daemon=False,
                )
                self._thread.start()
            if not inline:
                future: Future[Any] = Future()
                self._queue.put((function, future))
        if inline:
            return self._invoke(function)
        return future.result()

    def _invoke(self, function: Callable[[], Any]) -> Any:
        from app.core.runtime_artifacts import pinned_runtime_output_root

        # 每次进入均绑定本拥有者目录，不能继承调用线程或另一会话的路径。
        with ExitStack() as stack:
            if self._output_root is not None:
                stack.enter_context(pinned_runtime_output_root(self._output_root))
            if self._call_scope is not None:
                stack.enter_context(self._call_scope())
            return function()

    def close(self) -> None:
        with self._guard:
            thread = self._thread
            if thread is current_thread():
                raise RuntimeOwnerError("runtime_owner_self_close", "runtime owner cannot join itself")
            if thread is None:
                self._closed = True
                return
            if not self._closed:
                self._closed = True
                self._queue.put(_STOP)
        # 每个关闭调用都等待同一线程真正结束，不能把停止接纳当作已释放。
        thread.join()
        if self._terminal_error is not None:
            raise RuntimeOwnerError(
                "runtime_owner_finalization_failed",
                "runtime owner thread could not be finalized",
            ) from self._terminal_error

    def _run(self) -> None:
        self._thread_id = get_ident()
        initialized = False
        initialization_error: BaseException | None = None
        try:
            try:
                self._invoke(self._initializer)
                initialized = True
            except BaseException as error:  # 线程初始化失败须传给所有已排队调用
                initialization_error = error
            while True:
                item = self._queue.get()
                if item is _STOP:
                    return
                function, future = item
                if initialization_error is not None:
                    future.set_exception(
                        RuntimeOwnerError(
                            "runtime_owner_initialization_failed",
                            "runtime owner thread could not be initialized",
                        )
                    )
                    continue
                try:
                    future.set_result(self._invoke(function))
                except BaseException as error:
                    future.set_exception(error)
        finally:
            if initialized:
                try:
                    self._invoke(self._finalizer)
                except BaseException as error:
                    self._terminal_error = error


class RuntimeOwnerProxy:
    """仅把 host 所需方法送回原 owner，不创建第二套执行器。"""

    def __init__(self, owner: SerialRuntimeOwner, runtime: Any) -> None:
        self._owner = owner
        self._runtime = runtime

    def get_local_grounded_confirmation(self, **kwargs: Any) -> Any:
        return self._owner.call(
            lambda: self._runtime.get_local_grounded_confirmation(**kwargs)
        )

    def get_local_grounded_image(self, **kwargs: Any) -> bytes:
        return self._owner.call(lambda: self._runtime.get_local_grounded_image(**kwargs))

    def consume_grounded_confirmation(self, **kwargs: Any) -> Any:
        return self._owner.call(
            lambda: self._runtime.consume_grounded_confirmation(**kwargs)
        )

    def cancel_grounded_review(self, **kwargs: Any) -> Any:
        return self._owner.call(lambda: self._runtime.cancel_grounded_review(**kwargs))

    def release_local_fresh_recovery(self, **kwargs: Any) -> Any:
        return self._owner.call(lambda: self._runtime.release_local_fresh_recovery(**kwargs))


def _initialize_com() -> None:
    from ctypes import OleDLL, c_long

    ole32 = OleDLL("ole32")
    ole32.CoInitializeEx.restype = c_long
    result = int(ole32.CoInitializeEx(None, 0))
    if result not in {0, 1}:  # S_OK / S_FALSE
        raise OSError(result, "COM MTA initialization failed")


def _finalize_com() -> None:
    from ctypes import OleDLL

    OleDLL("ole32").CoUninitialize()


__all__ = ["RuntimeOwnerError", "RuntimeOwnerProxy", "SerialRuntimeOwner"]
