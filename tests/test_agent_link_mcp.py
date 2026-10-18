from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time

import pytest
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler

from tests.test_agent_link_inbox import _batch

ROOT = Path(__file__).resolve().parents[1]
SDK_PYTHON = Path(sys.executable)


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _post(url: str, token: str, payload: dict) -> dict:
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, method="POST")
    with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait(port: int) -> None:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("loopback inbox did not start")


def test_official_mcp_stdio_round_trip(tmp_path):
    mcp = pytest.importorskip("mcp")
    Client, StdioServerParameters = mcp.Client, mcp.StdioServerParameters

    port = _port()
    state = tmp_path / "inbox.json"
    environment = {**os.environ, "AGENT_LINK_REVIEWER_TOKEN": "reviewer-secret-value-123", "PYTHONIOENCODING": "utf-8"}
    server = subprocess.Popen([str(SDK_PYTHON), "scripts/start_agent_link_inbox.py", "--state-path", str(state), "--port", str(port)], cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        _wait(port)
        base = f"http://127.0.0.1:{port}"
        grant = _post(base + "/reviewer/create_connection", "reviewer-secret-value-123", {"task_id": "task-a", "agent_name": "sample"})
        bridge_env = {**os.environ, "AGENT_LINK_BASE_URL": base, "AGENT_LINK_TOKEN": grant["token"], "PYTHONIOENCODING": "utf-8"}
        parameters = StdioServerParameters(command=str(SDK_PYTHON), args=["scripts/start_agent_link_mcp.py"], env=bridge_env, cwd=ROOT)

        async def round_trip():
            async with Client(parameters) as client:
                tools = await client.list_tools()
                assert sorted(tool.name for tool in tools.tools) == ["agent_link_status", "read_learning_feedback", "submit_learning_batch", "submit_relearning_candidate"]
                batch_tool = next(tool for tool in tools.tools if tool.name == "submit_learning_batch")
                candidate_tool = next(tool for tool in tools.tools if tool.name == "submit_relearning_candidate")
                assert "regions" in json.dumps(batch_tool.input_schema) and "changes" in json.dumps(candidate_tool.input_schema)
                submitted = await client.call_tool("submit_learning_batch", {"batch": _batch()})
                receipt = json.loads(submitted.content[0].text)
                repeated = await client.call_tool("submit_learning_batch", {"batch": _batch()})
                assert receipt == json.loads(repeated.content[0].text) and receipt["status"] == "pending_review_proposal"
                _post(base + "/reviewer/record_feedback", "reviewer-secret-value-123", {"task_id": "task-a", "batch_id": "batch-a", "idempotency_key": "feedback", "expected_revision": 0, "notes": [], "issues": [{"issue_id": "issue-a", "scope": {"interface_ids": ["interface-list"], "relationship_ids": ["rel-a"]}, "message": "修改"}]})
                feedback = await client.call_tool("read_learning_feedback", {"batch_id": "batch-a"})
                assert json.loads(feedback.content[0].text)["revision"] == 1
                candidate = await client.call_tool("submit_relearning_candidate", {"candidate": {"contract_version": "agent_link_v1", "idempotency_key": "candidate", "batch_id": "batch-a", "issue_id": "issue-a", "baseline_revision": 1, "scope": {"interface_ids": ["interface-list"], "relationship_ids": ["rel-a"]}, "changes": [{"change_type": "geometry", "region_id": "region-row", "bbox": [0, 0, 15, 11]}]}})
                assert json.loads(candidate.content[0].text)["status"] == "pending_review_proposal"
        asyncio.run(round_trip())
        detail = _post(base + "/reviewer/get_batch", "reviewer-secret-value-123", {"task_id": "task-a", "batch_id": "batch-a"})
        assert detail["batch"]["interfaces"][0]["regions"] and len(detail["candidates"]) == 1
        server.terminate(); server.wait(timeout=5)
        server = subprocess.Popen([str(SDK_PYTHON), "scripts/start_agent_link_inbox.py", "--state-path", str(state), "--port", str(port)], cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        _wait(port)
        assert _post(base + "/reviewer/get_batch", "reviewer-secret-value-123", {"task_id": "task-a", "batch_id": "batch-a"})["candidates"][0]["status"] == "pending_review_proposal"
    finally:
        server.terminate()
        server.wait(timeout=5)
