from __future__ import annotations

import asyncio
import tomllib

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from app.agent_link.codex_config import render_codex_config
from tests.test_fresh_agent_stdio import _rig
from tests.test_formal_learning_runtime_controls import _mcp_server


def test_export_keeps_advertised_native_tools_visible_without_authorizing_input(tmp_path):
    # 只使用本轮临时数据、隔离宿主及真实 MCP 协议；不启动桌面或派发输入。
    with _rig(tmp_path) as (host, coordinator, connection, segment, staged, instances):
        parameters = _mcp_server(host.status()["base_url"], connection["token"])
        exported = tomllib.loads(render_codex_config({
            "command": parameters.command,
            "args": parameters.args,
            "env": parameters.env,
        }))["mcp_servers"]["agent_review"]

        async def check():
            async with stdio_client(parameters) as streams:
                async with ClientSession(*streams, read_timeout_seconds=60) as client:
                    await client.initialize()
                    descriptions = {tool.name: tool.description or "" for tool in (await client.list_tools()).tools}
                    advertised = set(descriptions)
                    assert {"observe_learning_screen", "start_learning_segment",
                            "prepare_fresh_learning_runtime", "request_fresh_learning_action",
                            "get_fresh_learning_runtime", "cancel_fresh_learning_runtime",
                            "finish_learning_segment"} <= advertised
                    assert advertised <= set(exported["enabled_tools"])
                    assert not any(name.startswith(("approve", "execute", "publish"))
                                   for name in exported["enabled_tools"])
                    # 未授权记忆范围时，客户端名单不能自行创造服务端能力。
                    assert "search_workflow_memory" not in advertised
                    assert "get_workflow_memory" not in advertised
                    assert "saved" in descriptions["search_interface_memory"]
                    assert "reviewed interface" not in descriptions["search_interface_memory"]
                    assert "without content approval" in descriptions["submit_learning_batch"]
                    assert instances == []

        asyncio.run(check())
