from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from threading import Event
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from app.agent_link.contracts import AgentLinkError
from app.agent_link.host import OwnedAgentLinkHttpHost
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore
from app.desktop_review.application_startup import ApplicationStartupProvider
from tests.test_catalog_window_preparation import catalog_host
from tests.test_window_preparation_authority import scene  # 注册 catalog_host 的场景依赖


REVIEWER = "application-startup-reviewer-secret"


class _Coordinator:
    def __init__(self):
        self.confirmed: list[str] = []
        self.fail_confirm = False

    def discover_applications(self):
        return {
            "contract_version": "native_application_discovery_v1",
            "apps": [{"app_id": "notes", "name": "Notes", "capabilities": ["observe"],
                      "executable_path": r"C:\Fixture\notes.exe", "launchable": True}],
            "running_windows": [],
        }

    def preview_application_launch(self, *, app_id: str, url: str | None = None):
        if app_id != "notes":
            raise ValueError("unknown")
        return {
            "contract_version": "native_window_preparation_v1", "preparation_id": "prepare-notes",
            "mode": "launch", "identity": None, "source": "app_catalog", "app_id": "notes", "name": "Notes",
            "url": url, "command": [r"C:\Fixture\notes.exe"] + ([url] if url else []),
            "executable_path": r"C:\Fixture\notes.exe", "catalog_entry_sha256": "a" * 64, "executable_sha256": "b" * 64, "expires_in_seconds": 60,
        }

    def confirm_window_preparation(self, preparation_id: str):
        self.confirmed.append(preparation_id)
        if self.fail_confirm:
            raise RuntimeError("synthetic uncertain dispatch")
        return {"status": "launched_window_ready", "process_id": 44,
                "window": {"handle": 77, "process_id": 44, "title": "Notes"}}


def _service(tmp_path):
    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, REVIEWER)
    coordinator = _Coordinator()
    provider = ApplicationStartupProvider(store, coordinator)
    service.bind_application_startup_provider(REVIEWER, provider)
    grant = service.reviewer_call(REVIEWER, "create_connection", {"task_id": "task-start", "agent_name": "agent"})
    return store, service, provider, coordinator, grant["token"]


def test_request_is_staged_then_human_preview_and_confirm_returns_window(tmp_path):
    store, service, provider, coordinator, token = _service(tmp_path)
    try:
        status = service.agent_call(token, "status", {})
        assert status["application_startup"]["operations"] == ["discover_applications", "request_application_launch", "get_application_launch"]
        assert service.agent_call(token, "discover_applications", {})["apps"][0]["app_id"] == "notes"
        request = service.agent_call(token, "request_application_launch", {"app_id": "notes", "url": "https://example.test/path", "idempotency_key": "launch-1"})
        assert request["status"] == "pending_human_confirmation" and request["staging_only"] is True
        assert coordinator.confirmed == []
        assert request == service.agent_call(token, "request_application_launch", {"app_id": "notes", "url": "https://example.test/path", "idempotency_key": "launch-1"})
        preview = provider.preview(request["request_id"])
        assert preview["command"] == [r"C:\Fixture\notes.exe", "https://example.test/path"]
        confirmed = provider.confirm(request["request_id"], preview["preview_sha256"])
        assert confirmed["status"] == "launched_window_ready" and confirmed["window"]["handle"] == 77
        result = service.agent_call(token, "get_application_launch", {"request_id": request["request_id"]})
        assert result["status"] == "launched_window_ready" and result["window"]["process_id"] == 44
        assert coordinator.confirmed == ["prepare-notes"]
    finally:
        store.close()


def test_confirmed_launch_receipt_survives_reopen_and_revocation_blocks_confirmation(tmp_path):
    store, service, provider, coordinator, token = _service(tmp_path)
    path = tmp_path / "inbox.json"
    try:
        request = service.agent_call(token, "request_application_launch", {"app_id": "notes", "idempotency_key": "persisted"})
        preview = provider.preview(request["request_id"])
        service.reviewer_call(REVIEWER, "revoke_connection", {"connection_id": service.agent_call(token, "status", {})["connection_id"], "idempotency_key": "revoke-startup"})
        with pytest.raises(AgentLinkError) as revoked:
            provider.confirm(request["request_id"], preview["preview_sha256"])
        assert revoked.value.code == "connection_revoked" and coordinator.confirmed == []
    finally:
        store.close()
    reopened = AgentLinkStore(path)
    try:
        record = next(iter(reopened.snapshot()["application_launches"]["requests"].values()))
        assert record["status"] == "previewed" and record["preview"]["command"] == [r"C:\Fixture\notes.exe"]
    finally:
        reopened.close()


def test_idempotency_cannot_replace_a_frozen_url_or_preview_before_confirmation(tmp_path):
    store, service, provider, coordinator, token = _service(tmp_path)
    try:
        request = service.agent_call(token, "request_application_launch", {"app_id": "notes", "url": "https://example.test/a", "idempotency_key": "frozen-url"})
        preview = provider.preview(request["request_id"])
        with pytest.raises(AgentLinkError) as conflict:
            service.agent_call(token, "request_application_launch", {"app_id": "notes", "url": "https://example.test/b", "idempotency_key": "frozen-url"})
        assert conflict.value.code == "idempotency_conflict"
        assert coordinator.confirmed == []
        outcome = provider.confirm(request["request_id"], preview["preview_sha256"])
        assert outcome["status"] == "launched_window_ready"
        assert coordinator.confirmed == [preview["preparation_id"]]
    finally:
        store.close()


def test_dispatch_started_is_durable_and_never_retries_after_unknown_confirm(tmp_path):
    store, service, provider, coordinator, token = _service(tmp_path)
    path = tmp_path / "inbox.json"
    try:
        request = service.agent_call(token, "request_application_launch", {"app_id": "notes", "idempotency_key": "launch-2"})
        preview = provider.preview(request["request_id"])
        coordinator.fail_confirm = True
        with pytest.raises(AgentLinkError) as error:
            provider.confirm(request["request_id"], preview["preview_sha256"])
        assert error.value.code == "launch_result_unknown" and coordinator.confirmed == ["prepare-notes"]
    finally:
        store.close()
    reopened = AgentLinkStore(path)
    try:
        assert reopened.snapshot()["application_launches"]["requests"][request["request_id"]]["status"] == "dispatch_started"
    finally:
        reopened.close()


def _port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _wait(port):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.03)
    raise AssertionError("host did not start")


def test_real_loopback_http_and_mcp_expose_only_staged_application_request(tmp_path):
    mcp = pytest.importorskip("mcp")
    store, service, _provider, coordinator, token = _service(tmp_path)
    host = OwnedAgentLinkHttpHost(service, port=0)
    try:
        base = host.start()
        port = int(base.rsplit(":", 1)[1])
        _wait(port)
        params = mcp.StdioServerParameters(command=sys.executable, args=["scripts/start_agent_review.py", "--agent-link-mcp"], cwd=str(Path(__file__).resolve().parents[1]), env={**os.environ, "AGENT_LINK_BASE_URL": base, "AGENT_LINK_TOKEN": token, "PYTHONIOENCODING": "utf-8"})
        async def round_trip():
            async with mcp.Client(params) as client:
                tools = await client.list_tools()
                names = {item.name for item in tools.tools}
                assert {"discover_applications", "request_application_launch", "get_application_launch"} <= names
                request_tool = next(item for item in tools.tools if item.name == "request_application_launch")
                assert "app_id" in json.dumps(request_tool.input_schema) and "command" not in json.dumps(request_tool.input_schema)
                request = await client.call_tool("request_application_launch", {"app_id": "notes", "idempotency_key": "stdio-1"})
                return json.loads(request.content[0].text)
        receipt = asyncio.run(round_trip())
        assert receipt["status"] == "pending_human_confirmation" and coordinator.confirmed == []
    finally:
        host.close()
        store.close()


def test_real_catalog_coordinator_stages_then_confirms_exact_preview(catalog_host):
    coordinator, _catalog, launched, _state, executable = catalog_host
    host = coordinator._host
    service = host._service
    grant = service.reviewer_call(host._reviewer_token, "create_connection", {"task_id": "首次学习目录", "agent_name": "agent"})
    request = service.agent_call(grant["token"], "request_application_launch", {"app_id": "fixture", "url": "https://example.org/search?q=place", "idempotency_key": "real-coordinator"})
    assert request["status"] == "pending_human_confirmation" and launched == []
    preview = host.application_startup.preview(request["request_id"])
    assert preview["command"] == [str(executable).casefold(), "https://example.org/search?q=place"]
    outcome = host.application_startup.confirm(request["request_id"], preview["preview_sha256"])
    assert outcome["status"] == "launched_window_ready"
    assert launched == [preview["command"]]
    result = service.agent_call(grant["token"], "get_application_launch", {"request_id": request["request_id"]})
    assert result["window"]["handle"] == 321 and result["window"]["process_id"] == 12


def test_dispatch_unknown_reopen_refuses_preview_and_confirm_without_second_launch(tmp_path):
    store, service, provider, coordinator, token = _service(tmp_path)
    path = tmp_path / "inbox.json"
    try:
        request = service.agent_call(token, "request_application_launch", {"app_id": "notes", "idempotency_key": "unknown-reopen"})
        preview = provider.preview(request["request_id"])
        coordinator.fail_confirm = True
        with pytest.raises(AgentLinkError) as unknown:
            provider.confirm(request["request_id"], preview["preview_sha256"])
        assert unknown.value.code == "launch_result_unknown" and coordinator.confirmed == ["prepare-notes"]
    finally:
        store.close()
    reopened = AgentLinkStore(path)
    retry_coordinator = _Coordinator()
    retry = ApplicationStartupProvider(reopened, retry_coordinator)
    try:
        with pytest.raises(AgentLinkError) as preview_rejected:
            retry.preview(request["request_id"])
        with pytest.raises(AgentLinkError) as confirm_rejected:
            retry.confirm(request["request_id"], preview["preview_sha256"])
        assert preview_rejected.value.code == "launch_not_available"
        assert confirm_rejected.value.code == "launch_not_available"
        assert retry_coordinator.confirmed == []
    finally:
        reopened.close()


def test_repreview_invalidates_old_digest_and_cross_connection_cannot_read(tmp_path):
    store, service, provider, coordinator, token = _service(tmp_path)
    try:
        request = service.agent_call(token, "request_application_launch", {"app_id": "notes", "idempotency_key": "repreview"})
        first = provider.preview(request["request_id"])
        original = coordinator.preview_application_launch
        def changed(*, app_id, url=None):
            value = original(app_id=app_id, url=url)
            return {**value, "preparation_id": "prepare-notes-new", "executable_sha256": "d" * 64}
        coordinator.preview_application_launch = changed
        second = provider.preview(request["request_id"])
        with pytest.raises(AgentLinkError) as stale:
            provider.confirm(request["request_id"], first["preview_sha256"])
        assert stale.value.code == "stale_preview" and coordinator.confirmed == []
        other = service.reviewer_call(REVIEWER, "create_connection", {"task_id": "task-start", "agent_name": "other"})
        with pytest.raises(AgentLinkError) as cross:
            service.agent_call(other["token"], "get_application_launch", {"request_id": request["request_id"]})
        assert cross.value.code == "not_found"
        provider.confirm(request["request_id"], second["preview_sha256"])
        assert coordinator.confirmed == ["prepare-notes-new"]
    finally:
        store.close()


def test_real_catalog_loopback_stdio_request_then_native_confirm_then_stdio_get(catalog_host):
    mcp = pytest.importorskip("mcp")
    coordinator, _catalog, launched, _state, executable = catalog_host
    host = coordinator._host
    service = host._service
    grant = service.reviewer_call(host._reviewer_token, "create_connection", {"task_id": "task-stdio", "agent_name": "agent"})
    base = host._base_url
    assert isinstance(base, str)
    parameters = mcp.StdioServerParameters(command=sys.executable, args=["scripts/start_agent_review.py", "--agent-link-mcp"], cwd=str(Path(__file__).resolve().parents[1]), env={**os.environ, "AGENT_LINK_BASE_URL": base, "AGENT_LINK_TOKEN": grant["token"], "PYTHONIOENCODING": "utf-8"})
    async def request_over_stdio():
        async with mcp.Client(parameters) as client:
            requested = await client.call_tool("request_application_launch", {"app_id": "fixture", "url": "https://example.org/search?q=stdio", "idempotency_key": "catalog-stdio"})
            initial = await client.call_tool("get_application_launch", {"request_id": json.loads(requested.content[0].text)["request_id"]})
            return json.loads(requested.content[0].text), json.loads(initial.content[0].text)
    request, initial = asyncio.run(request_over_stdio())
    assert initial["status"] == "pending_human_confirmation" and launched == []
    preview = host.application_startup.preview(request["request_id"])
    assert preview["command"] == [str(executable).casefold(), "https://example.org/search?q=stdio"]
    native = host.application_startup.confirm(request["request_id"], preview["preview_sha256"])
    assert native["window"]["handle"] == 321 and launched == [preview["command"]]
    async def get_over_stdio():
        async with mcp.Client(parameters) as client:
            result = await client.call_tool("get_application_launch", {"request_id": request["request_id"]})
            return json.loads(result.content[0].text)
    final = asyncio.run(get_over_stdio())
    assert final["status"] == "launched_window_ready" and final["window"]["process_id"] == 12
