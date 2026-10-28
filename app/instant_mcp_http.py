"""Authenticated loopback Streamable HTTP for the maintained instant MCP tools.

One negotiated MCP session owns this daemon's InstantSession. HTTP disconnects
do not release that owner. DELETE requires verified cleanup or explicit proof
that this Runtime instance never attempted startup or attached resources. It
never cancels or replays Runtime input. The SDK
owns JSON-RPC, protocol negotiation, tool dispatch and its session lifecycle.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from threading import Lock
from typing import Any

import anyio
from mcp.types import InitializeResult
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.instant_mcp import build_server


DEFAULT_TOKEN_ENV = "AGENT_GUI_MCP_TOKEN"
MAX_REQUEST_BYTES = 4 * 1024 * 1024
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
_HOST = re.compile(r"^127\.0\.0\.1(?::([0-9]{1,5}))?$")


def load_token_digest(token_env: str = DEFAULT_TOKEN_ENV) -> bytes:
    """Read only the named environment variable; never retain/log its value.

    Operators should generate this distinct connection secret with
    secrets.token_urlsafe(32). Syntax and obvious repetition can be checked here;
    no validator can prove that a caller supplied cryptographic randomness.
    """
    if not isinstance(token_env, str) or _ENV_NAME.fullmatch(token_env) is None:
        raise ValueError("HTTP token environment variable name is invalid")
    token = os.environ.get(token_env, "")
    if _TOKEN.fullmatch(token) is None or len(set(token)) < 12:
        raise ValueError("HTTP connection token must be a random URL-safe secret of 32..256 characters")
    return hashlib.sha256(token.encode("ascii")).digest()


def validate_bind(host: str, port: int) -> None:
    if host != "127.0.0.1":
        raise ValueError("HTTP MCP may bind only to 127.0.0.1")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("HTTP MCP port must be an integer in 0..65535")


async def _failure(scope: Scope, receive: Receive, send: Send, status: int,
                   code: str, message: str) -> None:
    headers = {"Cache-Control": "no-store"}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    response = JSONResponse({"error": {"code": code, "message": message}},
                            status_code=status, headers=headers)
    await response(scope, receive, send)


class InstantHttpMcpApp:
    """Admission/security around the SDK app, without serializing live RPCs.

    The short admission lock protects ownership and a POST counter, never a
    tool call. It lets status/cancel run during instant_run's receipt wait.
    Stateful initialize negotiation is required to establish an owner. The
    SDK's separate sessionless protocol cannot silently bypass that boundary.
    """

    def __init__(self, native_app: ASGIApp, session: Any, token_digest: bytes) -> None:
        self._native_app = native_app
        self._session = session
        self._token_digest = token_digest
        self._admission = anyio.Lock()
        self._owner: str | None = None
        self._protocol_version: str | None = None
        self._initializing = False
        self._deleting = False
        self._active_posts = 0
        self._close_guard = Lock()
        self._closed = False

    def close(self) -> None:
        """Service shutdown only; an HTTP session DELETE never calls this."""
        with self._close_guard:
            if not self._closed:
                self._session.close()
                self._closed = True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            async def lifecycle_send(message: Message) -> None:
                # Uvicorn may stop its event loop as soon as it observes this
                # acknowledgement. Finish Runtime cleanup before sending it.
                if message["type"] in {"lifespan.shutdown.complete", "lifespan.shutdown.failed", "lifespan.startup.failed"}:
                    with anyio.CancelScope(shield=True):
                        await anyio.to_thread.run_sync(self.close)
                await send(message)

            try:
                await self._native_app(scope, receive, lifecycle_send)
            finally:
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(self.close)
            return
        if scope["type"] != "http":
            await self._native_app(scope, receive, send)
            return

        # These checks precede body parsing, SDK session creation and JSON-RPC.
        headers: dict[bytes, list[bytes]] = {}
        for name, value in scope.get("headers", ()):
            headers.setdefault(name.lower(), []).append(value)
        authorization = headers.get(b"authorization", [])
        authenticated = False
        if len(authorization) == 1 and authorization[0].startswith(b"Bearer "):
            supplied = authorization[0][7:]
            authenticated = hmac.compare_digest(hashlib.sha256(supplied).digest(), self._token_digest)
        if not authenticated:
            await _failure(scope, receive, send, 401, "authentication_required", "Valid Bearer authentication is required")
            return
        client = scope.get("client")
        if client is None or client[0] != "127.0.0.1":
            await _failure(scope, receive, send, 403, "loopback_required", "Only 127.0.0.1 is permitted")
            return
        host_values = headers.get(b"host", [])
        host = host_values[0].decode("latin-1") if len(host_values) == 1 else ""
        match = _HOST.fullmatch(host)
        server = scope.get("server")
        host_port = int(match[1] or 80) if match else None
        if match is None or not 1 <= host_port <= 65535 or (server and host_port != server[1]):
            await _failure(scope, receive, send, 421, "host_forbidden", "Host must match the loopback listener")
            return
        if b"origin" in headers:
            await _failure(scope, receive, send, 403, "origin_forbidden", "Browser origins are not accepted")
            return
        if scope.get("path") != "/mcp":
            await _failure(scope, receive, send, 404, "endpoint_not_found", "MCP endpoint is /mcp")
            return
        for name in (b"mcp-session-id", b"mcp-protocol-version", b"content-length", b"content-type"):
            if len(headers.get(name, [])) > 1:
                await _failure(scope, receive, send, 400, "duplicate_header", "An MCP transport header is duplicated")
                return
        session_id = headers.get(b"mcp-session-id", [b""])[0].decode("latin-1")
        protocol = headers.get(b"mcp-protocol-version", [b""])[0].decode("latin-1")
        # The SDK has a distinct sessionless modern route. This transport needs
        # native initialize negotiation so each request belongs to one owner.
        if protocol and protocol not in HANDSHAKE_PROTOCOL_VERSIONS:
            await _failure(scope, receive, send, 400, "session_protocol_required", "Use native initialize negotiation for a stateful MCP session")
            return
        if scope["method"] == "DELETE":
            await self._delete(scope, receive, send, session_id, protocol)
            return
        if scope["method"] not in {"POST", "GET"}:
            await _failure(scope, receive, send, 405, "method_not_allowed", "MCP supports POST, GET and verified session DELETE")
            return

        body = b""
        is_initialize = False
        if scope["method"] == "POST":
            chunks = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunks.extend(message.get("body", b""))
                if len(chunks) > MAX_REQUEST_BYTES:
                    await _failure(scope, receive, send, 413, "request_too_large", "MCP request body exceeds the limit")
                    return
                if not message.get("more_body", False):
                    break
            body = bytes(chunks)
            try:
                payload = json.loads(body)
            except (UnicodeDecodeError, ValueError, RecursionError):
                payload = None
            is_initialize = isinstance(payload, dict) and payload.get("method") == "initialize"

        initial = False
        async with self._admission:
            rejection = self._owner_error(session_id, protocol)
            if self._owner is None and not self._initializing and not self._deleting and not session_id and is_initialize:
                self._initializing = True
                initial = True
                rejection = None
            elif self._owner is not None and is_initialize:
                rejection = (409, "owner_already_initialized", "Keep the original MCP session; verified DELETE releases its owner")
            if rejection is None and scope["method"] == "POST":
                self._active_posts += 1
        if rejection is not None:
            await _failure(scope, receive, send, *rejection)
            return

        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if scope["method"] == "POST" and not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        init_body = bytearray()
        init_messages: list[Message] = []
        init_status: int | None = None
        granted: bytes | None = None
        initial_committed = False
        initial_discarded = False

        async def owner_send(message: Message) -> None:
            nonlocal init_status, granted
            if initial:
                # HTTP 200 and a session header can also carry a JSON-RPC
                # initialization error. Commit neither headers nor ownership
                # until the SDK's complete result has been validated.
                init_messages.append(dict(message))
                if message["type"] == "http.response.start":
                    init_status = message["status"]
                    granted = dict(message.get("headers", ())).get(b"mcp-session-id")
                elif message["type"] == "http.response.body":
                    init_body.extend(message.get("body", b""))
                return
            await send(message)

        try:
            await self._native_app(scope, replay_receive, owner_send)
            if initial:
                negotiated = None
                try:
                    response = json.loads(init_body)
                    complete = any(message["type"] == "http.response.body" and not message.get("more_body", False)
                                   for message in init_messages)
                    if init_status == 200 and granted and complete and "error" not in response:
                        negotiated = InitializeResult.model_validate(response["result"])
                        if negotiated.protocol_version not in HANDSHAKE_PROTOCOL_VERSIONS:
                            negotiated = None
                except (ValueError, KeyError, TypeError):
                    negotiated = None
                if negotiated is not None:
                    async with self._admission:
                        self._owner = granted.decode("ascii")
                        self._protocol_version = negotiated.protocol_version
                        initial_committed = True
                elif granted:
                    with anyio.CancelScope(shield=True):
                        await self._discard_failed_initialize(scope, granted)
                    initial_discarded = True
                for message in init_messages:
                    await send(message)
        finally:
            with anyio.CancelScope(shield=True):
                if initial and granted and not initial_committed and not initial_discarded:
                    await self._discard_failed_initialize(scope, granted)
                async with self._admission:
                    if scope["method"] == "POST":
                        self._active_posts -= 1
                    if initial:
                        self._initializing = False

    async def _discard_failed_initialize(self, scope: Scope, session_id: bytes) -> None:
        """Terminate only the failed SDK handshake through its native DELETE.

        This session has never owned Runtime input. It must not call Runtime
        stop/close, nor pass through the verified-cleanup gate for real owners.
        """
        cleanup_scope = dict(scope)
        cleanup_scope["method"] = "DELETE"
        replaced = {b"mcp-session-id", b"mcp-protocol-version", b"content-length", b"content-type"}
        cleanup_scope["headers"] = [(key, value) for key, value in scope.get("headers", ())
                                    if key.lower() not in replaced]
        cleanup_scope["headers"].extend([(b"mcp-session-id", session_id),
                                         (b"mcp-protocol-version", HANDSHAKE_PROTOCOL_VERSIONS[-1].encode("ascii"))])
        status = None

        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]

        await self._native_app(cleanup_scope, receive, send)
        if status not in {200, 404}:
            raise RuntimeError("Failed MCP initialization session could not be terminated")

    def _owner_error(self, session_id: str, protocol: str) -> tuple[int, str, str] | None:
        if self._initializing or self._deleting:
            return 409, "owner_transition_pending", "Read the original session after its current lifecycle transition"
        if self._owner is None:
            return 409, "initialize_required", "Initialize one stateful MCP session before calling tools"
        if not session_id or not hmac.compare_digest(session_id.encode("latin-1"), self._owner.encode("ascii")):
            return 409, "input_owner_conflict", "Another MCP session owns this Runtime; reuse its original session ID"
        if protocol and self._protocol_version and protocol != self._protocol_version:
            return 400, "protocol_version_mismatch", "Use the version returned by native initialize negotiation"
        return None

    async def _delete(self, scope: Scope, receive: Receive, send: Send, session_id: str, protocol: str) -> None:
        async with self._admission:
            rejection = self._owner_error(session_id, protocol)
            if rejection is None and self._active_posts:
                rejection = (409, "requests_inflight", "Wait for original MCP requests and verify Runtime cleanup before DELETE")
            if rejection is None:
                self._deleting = True
        if rejection is not None:
            await _failure(scope, receive, send, *rejection)
            return
        try:
            try:
                status = await anyio.to_thread.run_sync(self._session.status)
                cold_instance = (status.get("phase") == "not_started"
                    and status.get("http_owner_release") == {
                        "schema": "instant_http_owner_release.v1", "state": "never_started_instance"})
                cleaned = (status.get("host_alive") is False and status.get("pending_ids") == []
                           and (status.get("cleanup_verified") is True or cold_instance))
            except Exception:
                cleaned = False
            if not cleaned:
                await _failure(scope, receive, send, 409, "runtime_cleanup_required", "Use instant_stop and inspect original receipts until Runtime cleanup is verified; DELETE does not cancel input")
                return

            async def released_send(message: Message) -> None:
                if message["type"] == "http.response.start" and 200 <= message["status"] < 300:
                    async with self._admission:
                        self._owner = None
                        self._protocol_version = None
                await send(message)

            await self._native_app(scope, receive, released_send)
        finally:
            with anyio.CancelScope(shield=True):
                async with self._admission:
                    self._deleting = False


def create_instant_http_app(session: Any, *, token_env: str = DEFAULT_TOKEN_ENV) -> InstantHttpMcpApp:
    """Build native HTTP MCP with environment-only authentication and one owner."""
    digest = load_token_digest(token_env)
    server = build_server(session)
    native_app = server.streamable_http_app(
        streamable_http_path="/mcp", json_response=True, stateless_http=False,
        max_request_body_size=MAX_REQUEST_BYTES, host="127.0.0.1",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1", "127.0.0.1:*"], allowed_origins=[]),
    )
    return InstantHttpMcpApp(native_app, session, digest)

