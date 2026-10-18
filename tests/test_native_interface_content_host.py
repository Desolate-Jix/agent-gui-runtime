"""全新隔离宿主中的独立界面公开能力。"""

import asyncio
import json
import os
from pathlib import Path
import sys

import mcp

from app.desktop_review.host import DesktopReviewHost
from tests.test_agent_link_inbox import _batch
from tests.test_agent_link_shared_host import _post


def test_native_host_advertises_interface_gateway_without_workflow_scope(tmp_path):
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", "fresh-interface-reviewer")
    try:
        ready = host.start()
        connection = host.connections.create_connection("fresh-interface-task", "isolated-agent")
        status, payload = _post(ready["base_url"] + "/agent/status", connection["token"], {})
        assert status == 200
        assert payload["interface_content"]["contract_version"] == "agent_interface_content_v1"
        assert set(payload["interface_content"]["operations"]) == {
            "search_interface_memory", "get_interface_memory", "request_interface_membership",
        }
        assert "workflow_memory" not in payload
        status, payload = _post(ready["base_url"] + "/agent/search_interface_memory", connection["token"], {})
        assert status == 200 and payload == []
    finally:
        host.close()


def test_real_stdio_submits_then_reads_saved_standalone_content_without_approval(tmp_path):
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", "fresh-interface-reviewer")
    try:
        ready = host.start()
        connection = host.connections.create_connection("fresh-interface-task", "isolated-agent")
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "WINDIR"}}
        env.update(AGENT_LINK_BASE_URL=ready["base_url"], AGENT_LINK_TOKEN=connection["token"],
                   PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        parameters = mcp.StdioServerParameters(command=sys.executable,
            args=["scripts/start_agent_link_mcp.py"], cwd=Path.cwd(), env=env)

        async def exercise():
            async with mcp.Client(parameters) as client:
                tools = await client.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {"search_interface_memory", "get_interface_memory", "request_interface_membership"} <= names
                assert "review_interface_content" not in names
                batch = _batch("fresh-interface-batch", "fresh-interface-import")
                batch["screenshots"] = batch["screenshots"][:1]
                batch["interfaces"] = batch["interfaces"][:1]
                batch.update(steps=[], relationships=[], issues=[])
                result = await client.call_tool("submit_learning_batch", {"batch": batch})
                assert not result.is_error
                submitted_ref = result.structured_content["interface_contents"][0]
                content = host.facade.import_interface_content(connection["task_id"], batch["batch_id"], "interface-list")
                assert submitted_ref["interface_id"] == content["interface_id"]
                assert submitted_ref["version_id"] == content["version_id"]
                assert not (tmp_path / "review" / "desktop-review" / "graph-revisions").exists()
                found = await client.call_tool("search_interface_memory", {})
                assert not found.is_error, found
                assert content["interface_id"] in str(found)
                exact = {key: content[key] for key in ("interface_id", "version_id")}
                assert content["review_status"] == "draft"
                direct = host.facade.get_interface_memory(connection["task_id"], **exact)
                assert host._service.agent_call(connection["token"], "get_interface_memory", exact) == direct
                result = await client.call_tool("get_interface_memory", exact)
                assert not result.is_error, result
                memory = json.loads(result.content[0].text)
                assert memory["interface_id"] == content["interface_id"]
                assert memory["version_id"] == content["version_id"]
                assert memory["content"]["meaning"] == batch["interfaces"][0]["meaning"]
                assert memory["execute_binding_enabled"] is False
                result = await client.call_tool("search_interface_memory", {})
                assert not result.is_error, result
                assert content["interface_id"] in str(result)
                graph = host.facade.create_workflow_graph("Fresh explicit workflow", connection["task_id"])
                membership = {**exact, "workflow_id": graph["logical_workflow_id"],
                    "expected_revision": graph["revision"], "expected_sha256": graph["content_sha256"],
                    "idempotency_key": "fresh-membership-request"}
                attached = await client.call_tool("request_interface_membership", membership)
                assert not attached.is_error, attached
                assert attached.structured_content["status"] == "saved"
                assert attached.structured_content["review_required"] is False
                assert attached.structured_content["execute_binding_enabled"] is False
                retry = await client.call_tool("request_interface_membership", membership)
                assert not retry.is_error and retry.structured_content == attached.structured_content
                saved_graph = host.facade.load_graph_revision(graph["logical_workflow_id"])
                assert saved_graph["revision"] == 2 and saved_graph["graph"]["edges"] == []
                foreign = host.connections.create_connection("unrelated-task", "foreign-agent")
                foreign_status, _ = _post(ready["base_url"] + "/agent/request_interface_membership", foreign["token"], membership)
                assert foreign_status == 400
                assert host.facade.load_graph_revision(graph["logical_workflow_id"]) == saved_graph
                resubmitted = await client.call_tool("submit_learning_batch", {"batch": batch})
                assert not resubmitted.is_error
                assert resubmitted.structured_content["interface_contents"][0] == submitted_ref
                version2 = host.facade.save_interface_content(content["interface_id"], content["revision"],
                    content["content_sha256"], {"meaning": "Later saved correction"}, "fresh-revision-2")
                pinned = await client.call_tool("get_interface_memory", exact)
                assert not pinned.is_error and pinned.structured_content["version_id"] == exact["version_id"]
                latest = await client.call_tool("get_interface_memory", {"interface_id": content["interface_id"]})
                assert not latest.is_error
                assert latest.structured_content["version_id"] == version2["version_id"]
                assert latest.structured_content["content"]["meaning"] == "Later saved correction"
                assert latest.structured_content["execute_binding_enabled"] is False
                assert host.facade.load_graph_revision(graph["logical_workflow_id"]) == saved_graph
        asyncio.run(exercise())
    finally:
        host.close()
