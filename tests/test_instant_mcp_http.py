"""Native MCP wire/security/lifecycle checks with harmless synthetic sessions."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
from threading import Event, RLock, Thread
import time

import httpx
import pytest
from starlette.testclient import TestClient
import uvicorn

from app.instant_mcp_http import create_instant_http_app, load_token_digest, validate_bind


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a0D8AAAAASUVORK5CYII=")


class HarmlessSession:
    """No desktop, real Runtime process, model or provider API is reachable."""

    def __init__(self, data_root):
        self.data_root = data_root
        self.session = data_root
        self.guard = RLock()
        self.closed = 0
        self.submissions = {}
        self.submitted = Event()
        self.settled = Event()
        self.stop_calls = 0
        self.state = {"host_alive": False, "pending_ids": [], "cleanup_verified": True}

    def start(self, new_session=False):
        return self.status()

    def status(self):
        return dict(self.state)

    def submit(self, request_id, command):
        if request_id in self.submissions:
            assert self.submissions[request_id] == command
            return self.result(request_id)
        self.submissions[request_id] = command
        if command["kind"] == "agent_command_cancel":
            self.settled.set()
            self.state = {"host_alive": False, "pending_ids": [], "cleanup_verified": True}
        else:
            self.state = {"host_alive": True, "pending_ids": [request_id], "cleanup_verified": False}
            self.submitted.set()
        return {"request_id": request_id, "status": "pending", "accepted": True}

    def result(self, request_id):
        return {"request_id": request_id, "status": "returned" if self.settled.is_set() else "pending"}

    def image(self, request_id, view="after"):
        return PNG

    def stop(self):
        self.stop_calls += 1
        self.state = {"host_alive": False, "pending_ids": [], "cleanup_verified": True}
        return self.status()

    def close(self):
        self.closed += 1


@pytest.fixture
def transport(tmp_path, monkeypatch):
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("AGENT_GUI_MCP_TOKEN", token)
    session = HarmlessSession(tmp_path)
    app = create_instant_http_app(session)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 51000)) as client:
        yield app, client, session, token
    assert session.closed == 1
    app.close()
    assert session.closed == 1


def headers(token, session_id=None):
    result = {"Authorization": "Bearer " + token, "Accept": "application/json, text/event-stream"}
    if session_id:
        result.update({"MCP-Session-Id": session_id, "MCP-Protocol-Version": "2025-11-25"})
    return result


def initialize(client, token, request_id=1):
    response = client.post("/mcp", headers=headers(token), json={
        "jsonrpc": "2.0", "id": request_id, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "harmless-http-test", "version": "1"}}})
    assert response.status_code == 200, response.text
    assert response.json()["result"]["protocolVersion"] == "2025-11-25"
    session_id = response.headers["mcp-session-id"]
    notified = client.post("/mcp", headers=headers(token, session_id), json={
        "jsonrpc": "2.0", "method": "notifications/initialized"})
    assert notified.status_code == 202, notified.text
    return session_id


def call(client, token, session_id, name, arguments=None, request_id=2):
    return client.post("/mcp", headers=headers(token, session_id), json={
        "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}}})


def test_native_initialize_tools_harmless_call_image_and_two_sessions(transport):
    app, client, session, token = transport
    ids = []
    for index in range(2):
        owner = initialize(client, token, request_id=10 * index + 1)
        ids.append(owner)
        listed = client.post("/mcp", headers=headers(token, owner), json={
            "jsonrpc": "2.0", "id": 10 * index + 2, "method": "tools/list", "params": {}})
        assert listed.status_code == 200
        names = {tool["name"] for tool in listed.json()["result"]["tools"]}
        assert {"instant_status", "instant_submit", "instant_run", "instant_stop", "instant_image"} <= names
        status = call(client, token, owner, "instant_status").json()["result"]
        assert json.loads(status["content"][0]["text"])["cleanup_verified"] is True
        image = call(client, token, owner, "instant_image", {"request_id": "original"}).json()["result"]
        content = image["content"][0]
        assert content["type"] == "image" and content["mimeType"] == "image/png"
        assert base64.b64decode(content["data"]) == PNG
        assert client.delete("/mcp", headers=headers(token, owner)).status_code == 200
        assert session.closed == 0
    assert ids[0] != ids[1]
    assert session.submissions == {} and session.stop_calls == 0


def test_failed_native_initialize_does_not_own_or_leak_session_and_allows_retry(transport):
    app, client, session, token = transport
    failed = client.post("/mcp", headers=headers(token), json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert failed.status_code == 200
    assert failed.json()["error"]["code"] == -32602
    failed_id = failed.headers["mcp-session-id"]
    assert app._owner is None and app._protocol_version is None
    assert not app._initializing and app._active_posts == 0
    # The SDK owns its transport registry. Native DELETE must have closed the
    # failed handshake's streams, without stopping/closing the Runtime session.
    manager = app._native_app.routes[0].endpoint.session_manager
    assert manager._server_instances[failed_id].is_terminated
    denied = call(client, token, failed_id, "instant_status")
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "initialize_required"
    assert session.submissions == {} and session.stop_calls == 0 and session.closed == 0

    for index in range(2):
        owner = initialize(client, token, request_id=10 + index)
        assert owner != failed_id and app._owner == owner
        status = call(client, token, owner, "instant_status")
        assert status.status_code == 200 and "error" not in status.json()
        assert call(client, token, failed_id, "instant_status").status_code == 409
        assert client.delete("/mcp", headers=headers(token, owner)).status_code == 200
        assert app._owner is None
    assert session.submissions == {} and session.stop_calls == 0 and session.closed == 0


@pytest.mark.parametrize("extra,expected", [
    ({"Authorization": "Bearer bad-token"}, 401),
    ({"Host": "evil.example"}, 421),
    ({"Host": "127.0.0.1:wrong"}, 421),
    ({"Host": "127.0.0.1:65000"}, 421),
    ({"Origin": "https://evil.example"}, 403),
    ({"Origin": "http://127.0.0.1"}, 403),
    ({"Origin": ""}, 403),
])
def test_security_precedes_protocol_and_owner_creation(transport, extra, expected):
    app, client, session, token = transport
    response = client.post("/mcp", headers={**headers(token), **extra}, content=b"not JSON")
    assert response.status_code == expected
    assert app._owner is None and not app._initializing
    assert token not in response.text
    assert session.submissions == {} and session.closed == 0


def test_missing_and_duplicate_token_rejected_before_native_app(transport):
    app, client, session, token = transport
    assert client.post("/mcp", content=b"bad").status_code == 401
    duplicate = [("Authorization", "Bearer " + token), ("Authorization", "Bearer " + token)]
    assert client.post("/mcp", headers=duplicate, content=b"bad").status_code == 401
    assert app._owner is None


def test_nonloopback_peer_rejected(tmp_path, monkeypatch):
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("AGENT_GUI_MCP_TOKEN", token)
    session = HarmlessSession(tmp_path)
    app = create_instant_http_app(session)
    with TestClient(app, base_url="http://127.0.0.1", client=("192.0.2.1", 1000)) as client:
        assert client.post("/mcp", headers=headers(token), content=b"bad").status_code == 403


def test_competing_initialize_wrong_owner_and_sessionless_bypass_rejected(transport):
    app, client, session, token = transport
    owner = initialize(client, token)
    second = client.post("/mcp", headers=headers(token), json={"jsonrpc": "2.0", "id": 8, "method": "initialize", "params": {}})
    assert second.status_code == 409
    assert call(client, token, "unrelated-session", "instant_status").status_code == 409
    assert call(client, token, None, "instant_status").status_code == 409
    modern = {**headers(token, owner), "MCP-Protocol-Version": "2026-07-28"}
    assert client.post("/mcp", headers=modern, json={"jsonrpc": "2.0", "id": 9, "method": "server/discover"}).status_code == 400
    assert app._owner == owner and session.submissions == {}


def test_disconnect_reconnect_preserves_original_owner_and_receipt(tmp_path, monkeypatch):
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("AGENT_GUI_MCP_TOKEN", token)
    session = HarmlessSession(tmp_path)
    app = create_instant_http_app(session)
    with loopback_daemon(app) as url:
        with httpx.Client(base_url=url[:-4]) as client:
            owner = initialize(client, token)
            submitted = call(client, token, owner, "instant_submit", {"request_id": "original", "command": {"kind": "capture"}})
            assert submitted.status_code == 200
        # A genuinely new TCP connection reuses the same logical MCP session.
        with httpx.Client(base_url=url[:-4]) as other:
            result = call(other, token, owner, "instant_result", {"request_id": "original", "detail": "full"})
            assert result.status_code == 200
            assert result.json()["result"]["structuredContent"]["request_id"] == "original"
            assert result.json()["result"]["structuredContent"]["status"] == "pending"
        assert app._owner == owner and list(session.submissions) == ["original"]
        assert session.stop_calls == 0


@pytest.mark.parametrize("state", [
    {"host_alive": True, "pending_ids": [], "cleanup_verified": True},
    {"host_alive": False, "pending_ids": ["original"], "cleanup_verified": True},
    {"host_alive": False, "pending_ids": [], "cleanup_verified": False},
    {"phase": "not_started", "host_alive": False, "pending_ids": [], "cleanup_verified": False},
    *({"phase": "not_started", "host_alive": False, "pending_ids": [], "cleanup_verified": False,
       "http_owner_release": proof} for proof in (
        None, False, {},
        {"schema": "instant_http_owner_release.v0", "state": "never_started_instance"},
        {"schema": "instant_http_owner_release.v1", "state": "unknown"},
    )),
    {"phase": "starting", "host_alive": False, "pending_ids": [], "cleanup_verified": False,
     "http_owner_release": {"schema": "instant_http_owner_release.v1", "state": "never_started_instance"}},
    {"phase": "not_started", "host_alive": True, "pending_ids": [], "cleanup_verified": False,
     "http_owner_release": {"schema": "instant_http_owner_release.v1", "state": "never_started_instance"}},
    {"phase": "not_started", "host_alive": False, "pending_ids": ["original"], "cleanup_verified": False,
     "http_owner_release": {"schema": "instant_http_owner_release.v1", "state": "never_started_instance"}},
    {},
])
def test_delete_cannot_release_unclean_or_unknown_runtime(transport, state):
    app, client, session, token = transport
    owner = initialize(client, token)
    session.state = state
    response = client.delete("/mcp", headers=headers(token, owner))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "runtime_cleanup_required"
    assert app._owner == owner and session.stop_calls == 0 and session.closed == 0


def test_status_and_cancel_can_run_during_original_receipt_wait(transport):
    app, client, session, token = transport
    owner = initialize(client, token)
    with ThreadPoolExecutor(max_workers=3) as pool:
        waiting = pool.submit(call, client, token, owner, "instant_run", {
            "request_id": "original", "command": {"kind": "capture"},
            "wait_ms": 5000, "images": "none", "detail": "full"}, 20)
        assert session.submitted.wait(2)
        status = pool.submit(call, client, token, owner, "instant_status", {}, 21).result(timeout=2)
        assert status.status_code == 200
        deleting = client.delete("/mcp", headers=headers(token, owner))
        assert deleting.status_code == 409 and deleting.json()["error"]["code"] == "requests_inflight"
        cancel = pool.submit(call, client, token, owner, "instant_submit", {
            "request_id": "cancel", "command": {"kind": "agent_command_cancel", "request": {"command_id": "original"}}}, 22).result(timeout=2)
        assert cancel.status_code == 200
        result = waiting.result(timeout=2)
    assert result.json()["result"]["structuredContent"]["status"] == "returned"
    assert list(session.submissions) == ["original", "cancel"]
    assert client.delete("/mcp", headers=headers(token, owner)).status_code == 200


@pytest.mark.parametrize("token", ["", "short", "x" * 64, "contains private spaces " * 3])
def test_bad_token_fails_closed_without_echo(monkeypatch, token):
    monkeypatch.setenv("AGENT_GUI_MCP_TOKEN", token)
    with pytest.raises(ValueError) as error:
        load_token_digest()
    if token:
        assert token not in str(error.value)


@pytest.mark.parametrize("host,port", [("0.0.0.0", 17665), ("localhost", 17665), ("::1", 17665), ("127.0.0.1", -1), ("127.0.0.1", True)])
def test_bind_is_explicitly_ipv4_loopback_only(host, port):
    with pytest.raises(ValueError):
        validate_bind(host, port)


@contextmanager
def loopback_daemon(app):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(32)
    port = listener.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="on", access_log=False,
                            log_level="critical", proxy_headers=False, timeout_graceful_shutdown=2)
    server = uvicorn.Server(config)
    thread = Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    try:
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        yield "http://127.0.0.1:" + str(port) + "/mcp"
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
        assert not thread.is_alive()


def test_loopback_daemon_shutdown_closes_session(tmp_path, monkeypatch):
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("AGENT_GUI_MCP_TOKEN", token)
    session = HarmlessSession(tmp_path)
    app = create_instant_http_app(session)
    with loopback_daemon(app) as url:
        with httpx.Client() as client:
            response = client.post(url, headers=headers(token), json={"jsonrpc": "2.0", "id": 1,
                "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                "clientInfo": {"name": "daemon-test", "version": "1"}}})
            assert response.status_code == 200
    assert session.closed == 1 and session.submissions == {}


def test_waiting_post_connection_timeout_never_replays_or_releases_owner(tmp_path, monkeypatch):
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("AGENT_GUI_MCP_TOKEN", token)
    session = HarmlessSession(tmp_path)
    app = create_instant_http_app(session)
    with loopback_daemon(app) as url:
        with httpx.Client(base_url=url[:-4]) as client:
            owner = initialize(client, token)
            with pytest.raises(httpx.ReadTimeout):
                client.post("/mcp", headers=headers(token, owner), timeout=.1, json={
                    "jsonrpc": "2.0", "id": 30, "method": "tools/call", "params": {
                        "name": "instant_run", "arguments": {"request_id": "original",
                        "command": {"kind": "capture"}, "wait_ms": 5000,
                        "detail": "full", "images": "none"}}})
        assert session.submitted.wait(2)
        with httpx.Client(base_url=url[:-4]) as other:
            assert call(other, token, owner, "instant_status").status_code == 200
            pending = call(other, token, owner, "instant_result", {"request_id": "original", "detail": "full"})
            assert pending.json()["result"]["structuredContent"]["status"] == "pending"
            cancelled = call(other, token, owner, "instant_submit", {"request_id": "cancel",
                "command": {"kind": "agent_command_cancel", "request": {"command_id": "original"}}})
            assert cancelled.status_code == 200
        assert app._owner == owner and list(session.submissions) == ["original", "cancel"]
        assert session.stop_calls == 0


def test_cli_finally_closes_session_when_server_startup_fails(tmp_path, monkeypatch):
    from app import instant_mcp
    from scripts import start_instant_mcp_http

    session = HarmlessSession(tmp_path)
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("AGENT_GUI_MCP_TOKEN", token)
    monkeypatch.setattr(instant_mcp, "InstantSession", lambda *args, **kwargs: session)

    class FailedServer:
        def __init__(self, config):
            assert config.host == "127.0.0.1" and config.port == 17665
            assert config.lifespan == "on"

        def run(self):
            raise RuntimeError("synthetic startup failure")

    monkeypatch.setattr(uvicorn, "Server", FailedServer)
    with pytest.raises(RuntimeError, match="synthetic startup failure"):
        start_instant_mcp_http.main(["--data-dir", str(tmp_path)])
    assert session.closed == 1 and session.submissions == {}


def test_runtime_close_finishes_before_lifespan_shutdown_acknowledgement(tmp_path, monkeypatch):
    import asyncio
    from app.instant_mcp_http import InstantHttpMcpApp

    session = HarmlessSession(tmp_path)

    async def native(scope, receive, send):
        await send({"type": "lifespan.startup.complete"})
        await send({"type": "lifespan.shutdown.complete"})

    app = InstantHttpMcpApp(native, session, b"not-a-real-secret")

    async def check():
        async def receive():
            raise AssertionError("unused")

        async def send(message):
            if message["type"] == "lifespan.shutdown.complete":
                assert session.closed == 1

        await app({"type": "lifespan"}, receive, send)

    asyncio.run(check())
    assert session.closed == 1


EXTERNAL_CLIENT = r'''
import asyncio, base64, json, os, sys
from httpx2 import AsyncClient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

async def check():
    outcomes = []
    async with AsyncClient(headers={"Authorization": "Bearer " + os.environ["AGENT_GUI_MCP_TOKEN"],
                                    "Accept": "application/json, text/event-stream"}) as http:
        failed = await http.post(sys.argv[1], json={"jsonrpc": "2.0", "id": 90,
            "method": "initialize", "params": {}})
        assert failed.status_code == 200 and failed.json()["error"]["code"] == -32602
        failed_id = failed.headers["mcp-session-id"]
        denied = await http.post(sys.argv[1], headers={"MCP-Session-Id": failed_id,
            "MCP-Protocol-Version": "2025-11-25"}, json={"jsonrpc": "2.0", "id": 91,
            "method": "tools/call", "params": {"name": "instant_status", "arguments": {}}})
        assert denied.status_code == 409
    for index in range(2):
        async with AsyncClient(headers={"Authorization": "Bearer " + os.environ["AGENT_GUI_MCP_TOKEN"]}) as http:
            transport = streamable_http_client(sys.argv[1], http_client=http)
            async with Client(transport, raise_exceptions=False) as client:
                listed = await client.list_tools()
                assert "instant_status" in {tool.name for tool in listed.tools}
                status = await client.call_tool("instant_status", {})
                assert json.loads(status.content[0].text)["cleanup_verified"] is True
                image = await client.call_tool("instant_image", {"request_id": "original"})
                assert image.content[0].type == "image"
                assert base64.b64decode(image.content[0].data).startswith(b"\x89PNG")
                outcomes.append({"protocol": client.protocol_version, "tools": len(listed.tools)})
    print(json.dumps(outcomes))

asyncio.run(check())
'''


@pytest.mark.skipif(not os.environ.get("AGENT_GUI_HTTP_TEST_CLIENT_PYTHON"), reason="External Host interpreter not selected")
def test_external_host_native_auto_negotiation_and_two_sessions(tmp_path, monkeypatch):
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("AGENT_GUI_MCP_TOKEN", token)
    session = HarmlessSession(tmp_path)
    app = create_instant_http_app(session)
    with loopback_daemon(app) as url:
        result = subprocess.run([os.environ["AGENT_GUI_HTTP_TEST_CLIENT_PYTHON"], "-I", "-", url],
                                input=EXTERNAL_CLIENT, text=True, capture_output=True, timeout=30,
                                env=dict(os.environ))
        assert result.returncode == 0, result.stderr
        outcomes = json.loads(result.stdout)
        assert len(outcomes) == 2 and {item["protocol"] for item in outcomes} == {"2025-11-25"}
    assert session.closed == 1 and session.submissions == {}
