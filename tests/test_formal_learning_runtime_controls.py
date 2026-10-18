from __future__ import annotations

from fastapi.testclient import TestClient

from app.agent_link.http_app import create_agent_link_app
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore


REVIEWER = "runtime-control-reviewer-token"
_RUNTIME_OPERATIONS = {
    "prepare_learning_runtime",
    "get_learning_runtime",
    "cancel_learning_runtime",
}


def test_runtime_preparation_is_not_exposed_without_a_trusted_provider(tmp_path):
    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, REVIEWER)
    connection = service.reviewer_call(REVIEWER, "create_connection", {
        "task_id": "fresh-runtime-task", "agent_name": "fresh-agent",
    })
    try:
        with TestClient(create_agent_link_app(service, reviewer_http=False),
                        client=("127.0.0.1", 45002)) as client:
            headers = {"Authorization": "Bearer " + connection["token"]}
            status = client.post("/agent/status", json={}, headers=headers)
            assert status.status_code == 200
            assert "learning_runtime" not in status.json()
            for operation in _RUNTIME_OPERATIONS:
                response = client.post("/agent/" + operation, json={
                    "connection_id": "client-injected",
                    "task_id": "client-injected",
                    "runtime_session_id": "client-injected",
                }, headers=headers)
                assert response.status_code == 400
                assert response.json()["error"]["code"] == "operation_forbidden"
    finally:
        store.close()

import asyncio
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.agent_link.host import OwnedAgentLinkHttpHost
from tests.test_native_learning_runtime_ingress import REVIEWER as NATIVE_REVIEWER, _prepare_args, _rig


_MCP_LEGACY = {
    "agent_link_status", "submit_learning_batch", "read_learning_feedback",
    "submit_relearning_candidate",
}


def _mcp_server(base_url: str, token: str) -> StdioServerParameters:
    environment = {key: os.environ[key] for key in ("SystemRoot", "PATH", "TEMP", "TMP") if key in os.environ}
    environment.update(
        AGENT_LINK_BASE_URL=base_url,
        AGENT_LINK_TOKEN=token,
        PYTHONIOENCODING="utf-8",
        PYTHONDONTWRITEBYTECODE="1",
        AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:",
    )
    return StdioServerParameters(
        command=sys.executable,
        args=["-c", "from app.agent_link.mcp_bridge import run_stdio; run_stdio()"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=environment,
    )


def test_runtime_stdio_prepares_real_callsite_and_cancels_scoped_child(tmp_path):
    with _rig(tmp_path) as (host, _coordinator, service, connection, segment, selection, backend, instances):
        other = service.reviewer_call(NATIVE_REVIEWER, "create_connection", {
            "task_id": connection["task_id"], "agent_name": "other-agent",
        })
        base_url = host.status()["base_url"]
        assert isinstance(base_url, str)
        first_server = _mcp_server(base_url, connection["token"])
        other_server = _mcp_server(base_url, other["token"])

        async def check() -> None:
            async with stdio_client(first_server) as first_streams:
                async with ClientSession(*first_streams, read_timeout_seconds=30) as first:
                    await first.initialize()
                    names = {tool.name for tool in (await first.list_tools()).tools}
                    assert _MCP_LEGACY | _RUNTIME_OPERATIONS <= names
                    prepared = await first.call_tool(
                        "prepare_learning_runtime", _prepare_args(segment, selection),
                    )
                    assert prepared.is_error is False
                    result = prepared.structured_content
                    assert result["phase"] == "observed", result
                    assert result["action_executed"] is False
                    assert len(instances) == 1 and backend.attempt_count == 0
                    current = await first.call_tool("get_learning_runtime", {
                        "segment_id": segment["segment_id"],
                        "preparation_id": result["preparation_id"],
                    })
                    assert current.is_error is False
                    assert current.structured_content["preparation_id"] == result["preparation_id"]
                    assert current.structured_content["session_id"] == instances[0]._observation.session_id
                    repeated = await first.call_tool(
                        "prepare_learning_runtime", _prepare_args(segment, selection),
                    )
                    assert repeated.is_error is False
                    assert repeated.structured_content["preparation_id"] == result["preparation_id"]
                    assert len(instances) == 1 and backend.attempt_count == 0
                    async with stdio_client(other_server) as other_streams:
                        async with ClientSession(*other_streams, read_timeout_seconds=30) as other_client:
                            await other_client.initialize()
                            denied = await other_client.call_tool("get_learning_runtime", {
                                "segment_id": segment["segment_id"],
                                "preparation_id": result["preparation_id"],
                            })
                            assert denied.is_error is True
                            text = "\n".join(item.text for item in denied.content if item.type == "text")
                            assert "not_found" in text and str(tmp_path) not in text
                    cancelled = await first.call_tool("cancel_learning_runtime", {
                        "segment_id": segment["segment_id"],
                        "preparation_id": result["preparation_id"],
                    })
                    assert cancelled.is_error is False
                    assert cancelled.structured_content["phase"] == "cancelled"
                    assert cancelled.structured_content["cleanup_verified"] is True

        asyncio.run(asyncio.wait_for(check(), timeout=60))
        child = service.agent_call(connection["token"], "get_learning_segment", {
            "segment_id": segment["segment_id"],
        })["children"]
        assert child[0]["phase"] == "cancelled"
        assert len(instances) == 1 and backend.attempt_count == 0


def test_runtime_stdio_without_provider_keeps_legacy_tools_only(tmp_path):
    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, REVIEWER)
    connection = service.reviewer_call(REVIEWER, "create_connection", {
        "task_id": "legacy-only", "agent_name": "legacy-agent",
    })
    host = OwnedAgentLinkHttpHost(service)
    try:
        base_url = host.start()

        async def check() -> None:
            async with stdio_client(_mcp_server(base_url, connection["token"])) as streams:
                async with ClientSession(*streams, read_timeout_seconds=30) as client:
                    await client.initialize()
                    assert {tool.name for tool in (await client.list_tools()).tools} == _MCP_LEGACY

        asyncio.run(asyncio.wait_for(check(), timeout=45))
    finally:
        try:
            host.close()
        finally:
            store.close()
