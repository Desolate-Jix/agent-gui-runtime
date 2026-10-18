"""学习段控制的真实服务、HTTP 与 MCP 通道，不发起桌面输入。"""

import asyncio
import json
import os
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.agent_link.contracts import AgentLinkError
from app.agent_link.host import OwnedAgentLinkHttpHost
from app.agent_link.http_app import create_agent_link_app
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore


REVIEWER = "segment-control-reviewer-token"
OPERATIONS = {"start_learning_segment", "get_learning_segment", "finish_learning_segment"}


def _connection(service):
    return service.reviewer_call(REVIEWER, "create_connection", {
        "task_id": "fresh-segment-task", "agent_name": "fresh-agent",
    })


def _install(service, store, root):
    assert callable(getattr(service, "bind_learning_segment_owner", None)), "real learning owner binding is missing"
    from app.agent.action_learning_recorder import ActionLearningRecorder
    from app.agent.action_learning_capture_archive import ActionLearningCaptureArchive
    from app.agent_link.learning_segments import LearningSegmentOwner

    recorder = ActionLearningRecorder(project_root=root)
    owner = LearningSegmentOwner(store, recorder=recorder,
                                 capture_archive=ActionLearningCaptureArchive(recorder=recorder))
    service.bind_learning_segment_owner(REVIEWER, owner)
    return owner


def test_http_empty_segment_roundtrip_reconnect_and_scope(tmp_path):
    path = tmp_path / "inbox.json"
    store = AgentLinkStore(path)
    service = AgentLinkService(store, REVIEWER)
    owner = _install(service, store, tmp_path)
    first, other = _connection(service), _connection(service)
    arguments = {"idempotency_key": "start-1", "title": "\u5bfb\u627e\u65b0\u5c97\u4f4d"}
    try:
        with TestClient(create_agent_link_app(service, reviewer_http=False),
                        client=("127.0.0.1", 45001)) as http:
            def call(operation, args, token=first["token"]):
                return http.post("/agent/" + operation, json=args,
                                 headers={"Authorization": "Bearer " + token})

            status = call("status", {}).json()
            assert set(status["learning_segments"]["operations"]) == OPERATIONS
            started = call("start_learning_segment", arguments)
            assert started.status_code == 200, started.text
            segment = started.json()
            assert segment["status"] == "active" and segment["children"] == []
            assert segment["action_executed"] is False
            assert call("start_learning_segment", arguments).json()["segment_id"] == segment["segment_id"]
            denied = call("get_learning_segment", {"segment_id": segment["segment_id"]}, other["token"])
            assert denied.json()["error"]["code"] == "not_found"
            injected = call("start_learning_segment", {**arguments, "runtime_session_id": "fake"})
            assert injected.json()["error"]["code"] == "invalid_arguments"
            assert call("attach_runtime", {"runtime_session_id": "fake"}).status_code == 404
            finished = call("finish_learning_segment", {
                "segment_id": segment["segment_id"], "expected_revision": segment["revision"],
            })
            assert finished.status_code == 200, finished.text
            closed = finished.json()
            assert closed["status"] == "closed" and closed["source_status"] == "empty"
            assert closed["artifact_is_authorization"] is False
            assert closed["execute_binding_enabled"] is False
        assert not owner.capture_archive.blobs_root.exists()
    finally:
        store.close()

    reopened = AgentLinkStore(path)
    try:
        resumed = AgentLinkService(reopened, REVIEWER)
        _install(resumed, reopened, tmp_path)
        actual = resumed.agent_call(first["token"], "get_learning_segment", {"segment_id": segment["segment_id"]})
        assert actual["status"] == "closed" and actual["source_status"] == "empty"
        assert actual["title"] == arguments["title"]
        assert str(tmp_path) not in json.dumps(actual)
    finally:
        reopened.close()


def test_controls_require_local_owner_and_reject_revoked_connection(tmp_path):
    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, REVIEWER)
    first = _connection(service)
    try:
        assert "learning_segments" not in service.agent_call(first["token"], "status", {})
        with pytest.raises(AgentLinkError) as missing:
            service.agent_call(first["token"], "start_learning_segment", {"idempotency_key": "one", "title": "new"})
        assert missing.value.code == "operation_forbidden"
        _install(service, store, tmp_path)
        service.reviewer_call(REVIEWER, "revoke_connection", {
            "connection_id": first["connection_id"], "idempotency_key": "revoke-1",
        })
        with pytest.raises(AgentLinkError) as revoked:
            service.agent_call(first["token"], "start_learning_segment", {"idempotency_key": "one", "title": "new"})
        assert revoked.value.code == "connection_revoked"
    finally:
        store.close()


@pytest.mark.parametrize("enabled", [False, True])
def test_actual_stdio_conditional_controls_and_safe_errors(tmp_path, enabled):
    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, REVIEWER)
    connection = _connection(service)
    if enabled:
        owner = _install(service, store, tmp_path)
    host = OwnedAgentLinkHttpHost(service)
    try:
        url = host.start()
        env = {key: os.environ[key] for key in ("SystemRoot", "PATH", "TEMP", "TMP") if key in os.environ}
        env.update(AGENT_LINK_BASE_URL=url, AGENT_LINK_TOKEN=connection["token"],
                   PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                   AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:")
        server = StdioServerParameters(command=sys.executable,
            args=["-c", "from app.agent_link.mcp_bridge import run_stdio; run_stdio()"],
            cwd=str(Path(__file__).resolve().parents[1]), env=env)

        async def check():
            with (tmp_path / "stdio-errors.log").open("w", encoding="utf-8") as log:
                async with stdio_client(server, errlog=log) as streams:
                    async with ClientSession(*streams, read_timeout_seconds=20) as client:
                        await client.initialize()
                        names = {item.name for item in (await client.list_tools()).tools}
                        legacy = {"agent_link_status", "submit_learning_batch", "read_learning_feedback", "submit_relearning_candidate"}
                        assert names == legacy | (OPERATIONS if enabled else set())
                        if not enabled:
                            return
                        reply = await client.call_tool("start_learning_segment", {"idempotency_key": "sdk-start", "title": "new learning"})
                        assert reply.is_error is False
                        segment = reply.structured_content
                        from tests.test_formal_learning_segments import _perform_action

                        recorded = [_perform_action(
                            tmp_path, owner, owner.recorder, owner.capture_archive,
                            connection, segment["segment_id"], sequence=sequence,
                        ) for sequence in (1, 2)]
                        read = await client.call_tool("get_learning_segment", {"segment_id": segment["segment_id"]})
                        assert read.is_error is False
                        current = read.structured_content
                        assert [item["runtime_session_id"] for item in current["children"]] == [item[0].session_id for item in recorded]
                        assert current["source_status"] == "complete"
                        assert current["action_executed"] is False
                        stale = await client.call_tool("finish_learning_segment", {
                            "segment_id": segment["segment_id"], "expected_revision": current["revision"] + 99,
                        })
                        assert stale.is_error is True
                        message = "\n".join(item.text for item in stale.content if item.type == "text")
                        assert "stale_revision" in message and str(tmp_path) not in message
                        done = await client.call_tool("finish_learning_segment", {
                            "segment_id": segment["segment_id"], "expected_revision": current["revision"],
                        })
                        assert done.is_error is False
                        assert done.structured_content["status"] == "closed"
                        assert done.structured_content["source_status"] == "complete"
                        assert done.structured_content["action_executed"] is False
                        assert len(done.structured_content["children"]) == 2
                        assert [item[2].attempt_count for item in recorded] == [1, 1]
        asyncio.run(asyncio.wait_for(check(), timeout=45))
    finally:
        try:
            host.close()
        finally:
            store.close()
