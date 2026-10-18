"""真实 MCP stdio 到 workflow-project memory 的隔离契约。"""
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import pytest

from app.agent_link.host import OwnedAgentLinkHttpHost
from tests.test_formal_agent_memory_reuse import _published_pair
from tests.test_formal_graph_exact_review import TASK, TOKEN


def test_real_stdio_reads_latest_and_fixed_project_snapshot(tmp_path: Path) -> None:
    inbox, facade, x, _first, _y, _second = _published_pair(tmp_path)
    service = facade._service
    fixed_view = facade.get_workflow_project_memory(TASK, x["logical_workflow_id"])
    service.bind_interface_content_gateway(TOKEN, facade)
    connection = service.reviewer_call(TOKEN, "create_connection", {
        "task_id": TASK, "agent_name": "fresh-project-stdio",
    })
    host = OwnedAgentLinkHttpHost(service)
    try:
        url = host.start()
        env = {key: os.environ[key] for key in ("SystemRoot", "PATH", "TEMP", "TMP") if key in os.environ}
        env.update(AGENT_LINK_BASE_URL=url, AGENT_LINK_TOKEN=connection["token"],
                   PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        params = StdioServerParameters(command=sys.executable,
            args=["-c", "from app.agent_link.mcp_bridge import run_stdio; run_stdio()"],
            cwd=str(Path(__file__).resolve().parents[1]), env=env)

        async def check() -> None:
            async with stdio_client(params) as streams:
                async with ClientSession(*streams, read_timeout_seconds=20) as client:
                    await client.initialize()
                    names = {item.name for item in (await client.list_tools()).tools}
                    assert {"search_workflow_projects", "get_workflow_project_memory"} <= names
                    assert "request_interface_membership" in names
                    search = await client.call_tool("search_workflow_projects", {})
                    assert search.is_error is False
                    items = search.structured_content["result"]
                    assert any(item["logical_workflow_id"] == x["logical_workflow_id"] for item in items)
                    fixed = await client.call_tool("get_workflow_project_memory", {
                        "workflow_id": x["logical_workflow_id"], "snapshot_id": fixed_view["snapshot_id"],
                    })
                    assert fixed.is_error is False
                    result = fixed.structured_content
                    assert result["logical_workflow_id"] == x["logical_workflow_id"]
                    assert result["snapshot_id"] == fixed_view["snapshot_id"]
                    assert result["execute_binding_enabled"] is False
                    assert result["artifact_is_authorization"] is False
                    assert "approve" not in json.dumps(result).casefold()

        asyncio.run(asyncio.wait_for(check(), timeout=45))
    finally:
        host.close()
        facade.close()
        inbox.close()
