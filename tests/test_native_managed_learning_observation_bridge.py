"""通过真实 HTTP/MCP 验证受管观察接线；仅替换系统与模型边界。"""

import asyncio
import base64
import os
from pathlib import Path
import sys

from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
from tests.test_native_managed_learning_observation import _managed_rig, _request, _close_managed


def test_managed_targeted_observation_crosses_real_mcp_and_preserves_one_graph(tmp_path, monkeypatch):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    host, coordinator, connection, segment, calls, trace, captures, _proof = _managed_rig(tmp_path, monkeypatch)
    # 实际 HTTP 宿主已启动，不替换协调器的就绪检查。
    coordinator._require_host_ready = NativeSingleStepCoordinator._require_host_ready.__get__(coordinator)
    try:
        host.start()
        environment = {key: os.environ[key] for key in ("SystemRoot", "PATH", "TEMP", "TMP") if key in os.environ}
        environment.update(AGENT_LINK_BASE_URL=host.status()["base_url"], AGENT_LINK_TOKEN=connection["token"],
            PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:")
        server = StdioServerParameters(command=sys.executable,
            args=["-c", "from app.agent_link.mcp_bridge import run_stdio; run_stdio()"],
            cwd=str(Path(__file__).resolve().parents[1]), env=environment)

        async def check():
            async with stdio_client(server) as streams:
                async with ClientSession(*streams, read_timeout_seconds=30) as client:
                    await client.initialize()
                    reply = await client.call_tool("observe_learning_screen", _request(segment))
                    assert reply.is_error is False, reply
                    content = reply.structured_content
                    image = next(item for item in reply.content if item.type == "image")
                    assert base64.b64decode(image.data) == captures[0].path.read_bytes()
                    assert "png_base64" not in content["screenshot"]
                    assert content["observation"]["recognition"]["status"] == "completed"
                    assert content["observation"]["recognition"]["goal"] == _request(segment)["goal"]
                    assert content["action_executed"] is False and content["artifact_is_authorization"] is False
                    graph = host.facade.load_graph_revision(content["logical_workflow_id"])
                    assert len(graph["graph"]["nodes"]) == 1 and graph["graph"]["edges"] == []
                    assert graph["graph"]["nodes"][0]["reviewed_by_human"] is False
                    repeated = await client.call_tool("observe_learning_screen", _request(segment))
                    assert repeated.is_error is False and repeated.structured_content == content
                    assert len(captures) == 1
        asyncio.run(asyncio.wait_for(check(), timeout=60))
        assert calls == {"load": 1, "freeze": 1, "factory": 1, "prepare": 1, "close": 1}
        assert len({thread_id for _event, thread_id in trace}) == 1
        assert coordinator.learning_runtime_state()["phase"] == "idle"
        assert host.facade.list_reviewed_assets() == []
    finally:
        _close_managed(coordinator, host)
