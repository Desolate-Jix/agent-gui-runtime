from __future__ import annotations

import contextlib
import contextvars
import http.client
import ipaddress
import io
import socket
import ssl
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request


class ModelRequestError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code.replace("_", " "))
        self.code = code
        self.computation_stopped = False


@dataclass(frozen=True)
class ModelRequestContext:
    cancelled: threading.Event
    verify_instance: Callable[[str, str], None] | None = None
    on_started: Callable[[str], None] | None = None
    on_completed: Callable[[str], None] | None = None
    on_cancelled: Callable[[str], Mapping[str, object]] | None = None

    def check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise ModelRequestError("model_request_cancelled", "model request cancelled")

    def check(self, endpoint: str, model_name: str) -> None:
        self.check_cancelled()
        if self.verify_instance is not None:
            self.verify_instance(endpoint, model_name)
        self.check_cancelled()

    @contextlib.contextmanager
    def request_scope(self, request_id: str) -> Iterator[None]:
        if self.on_started is not None:
            self.on_started(request_id)
        try:
            yield
        except ModelRequestError as error:
            if error.code == "model_request_cancelled" and self.on_cancelled is not None:
                proof = self.on_cancelled(request_id)
                error.computation_stopped = proof.get("computation_stopped") is True
                error.request_id = request_id
                error.cancel_status = str(proof.get("status") or "unverified")
            raise

    def request_completed(self, request_id: str) -> None:
        if self.on_completed is not None:
            self.on_completed(request_id)


_request_context: contextvars.ContextVar[ModelRequestContext | None] = contextvars.ContextVar(
    "model_request_context", default=None
)


def current_model_request() -> ModelRequestContext | None:
    return _request_context.get()


@contextlib.contextmanager
def pinned_model_request(context: ModelRequestContext) -> Iterator[ModelRequestContext]:
    token = _request_context.set(context)
    try:
        yield context
    finally:
        _request_context.reset(token)


def _validated_target(url: str) -> tuple[str, str, int, str]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ModelRequestError("model_request_unsafe_endpoint", "unsafe model request endpoint")
    hostname = parsed.hostname
    try:
        is_loopback = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        is_loopback = hostname.casefold() == "localhost"
    if not is_loopback:
        raise ModelRequestError("model_request_unsafe_endpoint", "unsafe model request endpoint")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ModelRequestError("model_request_unsafe_endpoint", "unsafe model request endpoint") from exc
    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    return parsed.scheme, hostname, port, target


def _shutdown_connection(connection: http.client.HTTPConnection) -> None:
    sock = getattr(connection, "sock", None)
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    connection.close()


class _CancellableRawSocket:
    """仅为 HTTPResponse 提供可取消的原始读取层。"""

    def __init__(self, sock: socket.socket, context: ModelRequestContext, deadline: float) -> None:
        self._sock = sock
        self._context = context
        self._deadline = deadline

    def makefile(self, mode: str, buffering: int | None = None):
        if mode != "rb":
            raise ValueError("model response requires binary reads")
        return io.BufferedReader(
            _CancellableRawIO(self._sock, self._context, self._deadline),
            buffering or io.DEFAULT_BUFFER_SIZE,
        )

    def shutdown(self, how: int) -> None:
        self._sock.shutdown(how)

    def close(self) -> None:
        # HTTPConnection 在 Connection: close 响应头后会关闭其套接字包装器；
        # 响应体仍由此原始读取器消费，实际关闭由请求 finally 统一执行。
        return None


class _CancellableRawIO(io.RawIOBase):
    def __init__(self, sock: socket.socket, context: ModelRequestContext, deadline: float) -> None:
        self._sock = sock
        self._context = context
        self._deadline = deadline

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        while True:
            self._context.check_cancelled()
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise ModelRequestError("model_request_timeout", "model request timed out")
            try:
                self._sock.settimeout(min(0.1, remaining))
                return self._sock.recv_into(buffer)
            except socket.timeout:
                continue
            except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                continue
            except OSError as exc:
                if self._context.cancelled.is_set():
                    self._context.check_cancelled()
                raise


def read_cancellable_response(request: Request, *, timeout: float, context: ModelRequestContext) -> bytes:
    context.check_cancelled()
    scheme, hostname, port, target = _validated_target(request.full_url)
    connection_class = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    connection = connection_class(hostname, port, timeout=timeout)
    watcher_done = threading.Event()
    socket_ready = threading.Event()
    active_socket: socket.socket | None = None
    deadline = time.monotonic() + timeout

    def watch_cancellation() -> None:
        while not watcher_done.is_set() and not context.cancelled.is_set():
            context.cancelled.wait(0.05)
        if context.cancelled.is_set():
            if socket_ready.wait(0.1) and active_socket is not None:
                try:
                    active_socket.settimeout(0.1)
                    active_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    active_socket.close()
                except OSError:
                    pass

    watcher = threading.Thread(target=watch_cancellation, name="model-request-cancel", daemon=True)
    watcher.start()
    try:
        context.check_cancelled()
        data = request.data.encode("utf-8") if isinstance(request.data, str) else request.data
        try:
            # 显式连接以便取消观察线程始终能取得并关闭活动套接字。
            connection.connect()
            active_socket = connection.sock
            socket_ready.set()
            context.check_cancelled()
            connection.request(request.get_method(), target, body=data, headers=dict(request.header_items()))
            context.check_cancelled()
            connection.sock = _CancellableRawSocket(active_socket, context, deadline)
            response = connection.getresponse()
            body = response.read()
        except ModelRequestError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            if context.cancelled.is_set():
                context.check_cancelled()
            raise ModelRequestError("model_request_transport_failed", str(exc)) from exc
        context.check_cancelled()
        if not 200 <= response.status < 300:
            raise HTTPError(request.full_url, response.status, response.reason, response.headers, BytesIO(body))
        return body
    finally:
        watcher_done.set()
        _shutdown_connection(connection)
        if active_socket is not None:
            try:
                active_socket.close()
            except OSError:
                pass
        watcher.join(timeout=1.0)
