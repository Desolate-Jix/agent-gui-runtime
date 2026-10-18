"""Agent Link 的宿主拥有型 loopback HTTP 生命周期。"""

from __future__ import annotations

import asyncio
import math
import os
import socket
import threading
import time
from typing import Any

import uvicorn

from .http_app import create_agent_link_app


class AgentLinkHttpHostError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(message)


class OwnedAgentLinkHttpHost:
    """只管理本实例创建的 socket、Uvicorn server 与线程。"""

    def __init__(
        self,
        service: Any,
        *,
        port: int = 0,
        execution_controller: Any | None = None,
        execution_token_digest: str | None = None,
    ) -> None:
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise AgentLinkHttpHostError("invalid_port", "port must be 0 or in 1..65535")
        self._service = service
        if (execution_controller is None) != (execution_token_digest is None):
            raise AgentLinkHttpHostError(
                "invalid_execution_adapter",
                "execution controller and token digest must be provided together",
            )
        self._execution_controller = execution_controller
        self._execution_token_digest = execution_token_digest
        self._requested_port = port
        self._guard = threading.RLock()
        self._phase = "created"
        self._base_url: str | None = None
        self._socket: socket.socket | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._failure: BaseException | None = None

    @property
    def phase(self) -> str:
        with self._guard:
            return self._phase

    @property
    def base_url(self) -> str | None:
        with self._guard:
            return self._base_url if self._phase == "ready" else None

    def start(self, *, timeout: float = 5.0) -> str:
        wait = _timeout(timeout)
        with self._guard:
            if self._phase == "ready":
                return str(self._base_url)
            if self._phase != "created":
                raise AgentLinkHttpHostError("invalid_phase", "HTTP host cannot be started in its current phase")
            self._phase = "starting"
            listener: socket.socket | None = None
            try:
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                if os.name == "nt":
                    listener.setsockopt(
                        socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1
                    )
                else:
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", self._requested_port))
                listener.listen(2048)
                listener.setblocking(False)
            except OSError as error:
                if listener is not None:
                    listener.close()
                self._phase = "failed"
                raise AgentLinkHttpHostError("bind_failed", "loopback HTTP port could not be bound") from error
            port = int(listener.getsockname()[1])
            try:
                config = uvicorn.Config(
                    create_agent_link_app(
                        self._service,
                        reviewer_http=False,
                        execution_controller=self._execution_controller,
                        execution_token_digest=self._execution_token_digest,
                    ),
                    host="127.0.0.1", port=port, workers=1,
                    # 原生无控制台启动没有 stdout，不能让日志格式器探测终端颜色。
                    access_log=False, log_level="warning", use_colors=False, proxy_headers=False,
                    forwarded_allow_ips="", lifespan="off",
                    timeout_graceful_shutdown=None,
                )
                self._socket = listener
                self._server = uvicorn.Server(config)
                self._thread = threading.Thread(
                    target=self._run, name=f"agent-link-http-{port}", daemon=False
                )
                self._thread.start()
            except Exception as error:
                self._socket = None
                self._server = None
                self._thread = None
                listener.close()
                self._phase = "failed"
                raise AgentLinkHttpHostError(
                    "startup_failed", "loopback HTTP server could not be prepared"
                ) from error

        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            with self._guard:
                server, thread = self._server, self._thread
                if server is not None and server.started and thread is not None and thread.is_alive():
                    self._phase = "ready"
                    self._base_url = f"http://127.0.0.1:{port}"
                    return self._base_url
                if thread is None or not thread.is_alive():
                    self._phase = "failed"
                    raise AgentLinkHttpHostError("startup_failed", "loopback HTTP server did not start")
            time.sleep(0.01)
        with self._guard:
            self._phase = "stopping"
        self._request_shutdown()
        thread = self._thread
        if thread is not None:
            thread.join(wait)
        if thread is None or not thread.is_alive():
            self._close_listener()
            with self._guard:
                self._phase = "failed"
        raise AgentLinkHttpHostError("startup_timeout", "loopback HTTP server readiness timed out")

    def close(self, *, timeout: float = 5.0) -> None:
        wait = _timeout(timeout)
        with self._guard:
            if self._phase == "stopped":
                return
            if self._phase == "created":
                self._phase = "stopped"
                return
            self._phase = "stopping"
        self._request_shutdown()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(wait)
        if thread is not None and thread.is_alive():
            raise AgentLinkHttpHostError(
                "shutdown_timeout", "loopback HTTP server is still draining"
            )
        self._close_listener()
        with self._guard:
            self._base_url = None
            self._phase = "stopped"

    def _run(self) -> None:
        loop: asyncio.AbstractEventLoop | None = None
        try:
            loop = asyncio.new_event_loop()
            with self._guard:
                self._loop = loop
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._server.serve(sockets=[self._socket]))
        except BaseException as error:
            with self._guard:
                self._failure = error
        finally:
            if loop is not None and not loop.is_closed():
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                finally:
                    loop.close()
            asyncio.set_event_loop(None)
            with self._guard:
                if self._phase not in {"stopping", "stopped"}:
                    self._phase = "failed"
                    self._base_url = None
                self._loop = None
            self._close_listener()

    def _request_shutdown(self) -> None:
        with self._guard:
            server, loop = self._server, self._loop
            if server is not None:
                server.should_exit = True
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(self._stop_accepting)
            except RuntimeError:
                pass

    def _stop_accepting(self) -> None:
        server = self._server
        for listener in getattr(server, "servers", ()) if server is not None else ():
            listener.close()

    def _close_listener(self) -> None:
        with self._guard:
            listener, self._socket = self._socket, None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass


def _timeout(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise AgentLinkHttpHostError("invalid_timeout", "timeout must be positive")
    return float(value)
